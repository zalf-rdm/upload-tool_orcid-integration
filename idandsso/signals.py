#         Copyright (C) 2026 52°North Spatial Information Research GmbH
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     If the program is linked with libraries which are licensed under one
#     of the following licenses, the combination of the program with the
#     linked library is not considered a "derivative work" of the program:
#
#         - Apache License, version 2.0
#         - Apache Software License, version 1.0
#         - GNU Lesser General Public License, version 3
#         - Mozilla Public License, versions 1.0, 1.1 and 2.0
#         - Common Development and Distribution License (CDDL), version 1.0
#
#     Therefore the distribution of the program linked with libraries licensed
#     under the aforementioned licenses, is permitted by the copyright holders
#     if the distribution is compliant with both the GNU General Public License
#     version 2 and the aforementioned licenses.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program. If not, see <https://www.gnu.org/licenses/>.

#
#   receive/handle user sign up and user updated events to sync the groups of this user
#
#   SocialAccount signals
#
#       https://docs.allauth.org/en/dev/socialaccount/signals.html
#

from allauth.account.signals import user_logged_in
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import (
    Group,
    User,
)
from django.db import transaction
from django.db.models.signals import (
    m2m_changed,
    post_save,
)
from django.dispatch import receiver
from loguru import logger

from .keycloak import (
    add_user_to_keycloak_group,
    remove_user_from_keycloak_group,
)
from .utils import sso_cookie_domain


@receiver(signal=user_logged_in)
def handle_user_logged_in(sender, request, response, user, **kwargs):
    """
    - receives local and social logins
      - later after social_account_updated
    - ensure group membership
    - ensure staff and superuser status
    """
    logger.debug("signal 'user_logged_in' received")
    if not _is_social_account(user):
        return
    social_user = SocialAccount.objects.get(user=user)
    social_groups = (
        set(social_user.extra_data.get("id_token").get("groups"))
        if social_user.extra_data.get("id_token").get("groups")
        else set()
    )
    affiliation = (
        social_user.extra_data.get("userinfo").get("affiliation")
        if social_user.extra_data.get("userinfo").get("affiliation")
        else {}
    )

    _ensure_staff_and_superuser_status(user, social_groups)
    _ensure_user_affiliation(user, affiliation)

    # local_groups: currently assigned groups in django
    local_groups = set(user.groups.values_list("name", flat=True))
    # social_groups: groups assigned in keycloak (mapped to django group names)
    social_groups = _map_social_groups(social_groups)
    groups_to_add = social_groups - local_groups
    groups_to_remove = local_groups - social_groups
    if groups_to_add:
        _add_user_to_groups(user, groups_to_add)
    if groups_to_remove:
        _remove_user_from_groups(user, groups_to_remove)
    #
    #   set cookie for single sign on
    #
    if response and "sso_hint" not in request.COOKIES:
        domain = sso_cookie_domain()
        max_age = getattr(settings, "SESSION_COOKIE_AGE", 3600)
        logger.debug(f"Domain for cookie: '{domain}'")
        response.set_cookie(
            "sso_hint",
            "true",
            domain=domain,
            max_age=max_age,
            samesite="Lax",
            path="/",
            secure=request.is_secure(),
            httponly=False,
        )


@receiver(signal=post_save, sender=settings.AUTH_USER_MODEL)
def handle_group_updates_post_save(sender, instance, **kwargs):
    """
    https://docs.djangoproject.com/en/5.1/ref/signals/#post-save
    """
    if (
        not _is_social_account(instance)
        or _is_login_event(kwargs.get("update_fields"))
        or getattr(instance, "_skip_keycloak_sync_because_of_login", False)
    ):
        return
    logger.debug(f"post_save signal received from '{sender}' for '{instance}'")
    add_groups = []
    remove_groups = []
    # update superuser group
    if instance.is_superuser:
        add_groups += [settings.IDANDSSO_GROUP_NAME_DJANGO_SUPERUSER]
    else:
        remove_groups += [settings.IDANDSSO_GROUP_NAME_DJANGO_SUPERUSER]
    # update staff group
    if instance.is_staff:
        add_groups += [settings.IDANDSSO_GROUP_NAME_DJANGO_STAFF]
    else:
        remove_groups += [settings.IDANDSSO_GROUP_NAME_DJANGO_STAFF]
    # trigger processing
    if len(add_groups) > 0:
        transaction.on_commit(lambda: _process_sync([instance], add_groups, is_add=True))
    if len(remove_groups) > 0:
        transaction.on_commit(lambda: _process_sync([instance], remove_groups, is_add=False))
    # updating groups is done in sync_group_changes_with_keycloak()


@receiver(signal=m2m_changed, sender=get_user_model().groups.through)
def sync_group_changes_with_keycloak(sender, instance, action, pk_set, reverse, **kwargs):
    """
    https://docs.djangoproject.com/en/5.1/ref/signals/#m2m-changed
    """
    if action in ["post_add", "post_remove"]:
        logger.debug(
            f"m2m_changed.(post_add|post_remove) signal received from '{sender}' for '{instance}'"
        )
        is_add = action == "post_add"
        users, groups = _get_targets(instance, pk_set, reverse)
        # Trigger sync after successful DB commit
        transaction.on_commit(lambda: _process_sync(users, groups, is_add=is_add))
    elif action == "pre_clear":
        logger.debug(f"m2m_changed.pre_clear signal received from '{sender}' for '{instance}'")
        groups, users = None, None
        if reverse:
            groups = [instance]
            users = list(instance.user_set.all())
        else:
            users = [instance]
            groups = list(instance.groups.all())

        transaction.on_commit(lambda: _process_sync(users, groups, is_add=False))


def _ensure_staff_and_superuser_status(user, social_groups):
    logger.debug(f"_ensure_staff_and_superuser_status({user.username}, {social_groups})")
    update_fields = []
    is_django_staff = settings.IDANDSSO_GROUP_NAME_DJANGO_STAFF in social_groups
    is_django_staff_before = user.is_staff
    if is_django_staff != is_django_staff_before:
        user.is_staff = is_django_staff
        update_fields += ["is_staff"]

    is_django_superuser = settings.IDANDSSO_GROUP_NAME_DJANGO_SUPERUSER in social_groups
    is_django_superuser_before = user.is_superuser
    if is_django_superuser != is_django_superuser_before:
        user.is_superuser = is_django_superuser
        update_fields += ["is_superuser"]

    if len(update_fields) > 0:
        user._skip_keycloak_sync_because_of_login = True
        user.save(update_fields=update_fields)


def _ensure_user_affiliation(user, affiliation):
    """
    Using ORCID API affiliation

    See https://github.com/ORCID/orcid-model
    """
    logger.debug(f"_ensure_user_affiliation({user.username}, affiliation)")
    org_name = (
        affiliation.get("organization").get("name") if affiliation.get("organization") else None
    )
    if not org_name:
        logger.debug("end processing affiliation information, because no org_name is found.")
        return
    org_ror = (
        affiliation.get("organization")
        .get("disambiguated-organization")
        .get("disambiguated-organization-identifier")
        if affiliation.get("organization")
        and affiliation.get("organization").get("disambiguated-organization")
        and affiliation.get("organization")
        .get("disambiguated-organization")
        .get("disambiguation-source")
        and affiliation.get("organization")
        .get("disambiguated-organization")
        .get("disambiguation-source")
        == "ROR"
        else None
    )
    logger.debug(f"Found affiliation: '{org_name}' ('{org_ror}')")
    update_fields = []
    if user.organization != org_name:
        user.organization = org_name
        update_fields += ["organization"]
    if user.rorlink != org_ror:
        user.rorlink = org_ror
        update_fields += ["rorlink"]

    if len(update_fields) > 0:
        user._skip_keycloak_sync_because_of_login = True
        user.save(update_fields=update_fields)


def _map_social_groups(social_groups):
    if settings.IDANDSSO_GROUP_MAP:
        mapped_groups = set()
        for social_group in social_groups:
            if social_group in [
                settings.IDANDSSO_GROUP_NAME_DJANGO_STAFF,
                settings.IDANDSSO_GROUP_NAME_DJANGO_SUPERUSER,
            ]:
                continue
            mapped_group = settings.IDANDSSO_GROUP_MAP.get(social_group)
            if not mapped_group:
                logger.error(f"No mapping found for social group '{social_group}'")
            else:
                mapped_groups.add(mapped_group)
        social_groups = mapped_groups
    return social_groups


def _add_user_to_groups(user, groups_to_add):
    logger.debug(f"_add_user_to_groups({user.username}, {groups_to_add})")
    django_groups_to_add = list(Group.objects.filter(name__in=groups_to_add))
    user.groups.add(*django_groups_to_add)
    added_group_names = {g.name for g in django_groups_to_add}
    logger.debug(f"Added user '{user.username}' to groups: '{added_group_names}'")
    missing_groups = groups_to_add - added_group_names
    if missing_groups:
        logger.error(
            f"Could not add user '{user.username}' to '{missing_groups}' because they do NOT EXIST."
        )


def _remove_user_from_groups(user, groups_to_remove):
    logger.debug(f"_remove_user_from_groups({user.username}, {groups_to_remove})")
    django_groups_to_remove = list(Group.objects.filter(name__in=groups_to_remove))
    user.groups.remove(*django_groups_to_remove)
    removed_group_names = {g.name for g in django_groups_to_remove}
    logger.debug(f"Remove '{user.username}' from groups: '{removed_group_names}'")
    missing_groups = groups_to_remove - removed_group_names
    if missing_groups:
        logger.error(
            f"Could not remove user '{user.username}' from '{missing_groups}' because they do NOT EXIST."
        )


def _is_login_event(updated_fields: frozenset) -> bool:
    if updated_fields and len(updated_fields) == 1 and "last_login" in updated_fields:
        return True
    return False


def _is_social_account(user: settings.AUTH_USER_MODEL) -> bool:
    try:
        SocialAccount.objects.get(user=user)
        return True
    except SocialAccount.DoesNotExist:
        return False
    return False


IDANDSSO_GROUP_MAP_REVERSE = {v: k for k, v in settings.IDANDSSO_GROUP_MAP.items()}


def _get_targets(instance, pk_set: (int), reverse: bool) -> ((settings.AUTH_USER_MODEL), (Group)):
    if reverse:
        # Change via group (Group Admin) -> instance is group
        groups = [instance]
        users = User.objects.filter(pk__in=pk_set)
    else:
        # Change via User (User Admin) -> instance is User
        users = [instance]
        groups = Group.objects.filter(pk__in=pk_set)
    keycloak_group_names = {IDANDSSO_GROUP_MAP_REVERSE.get(g.name) for g in groups}
    return users, keycloak_group_names


def _process_sync(
    users: (settings.AUTH_USER_MODEL), keycloak_group_names: (str), is_add: bool
) -> None:
    for user in users:
        if _is_social_account(user):
            for group_name in keycloak_group_names:
                try:
                    if is_add:
                        add_user_to_keycloak_group(user, group_name)
                    else:
                        remove_user_from_keycloak_group(user, group_name)
                except Exception as e:
                    logger.error(f"Error while syncing groups with keycloak: {e}")
