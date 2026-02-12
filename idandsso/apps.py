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

from django.apps import AppConfig
from django.conf import settings
from loguru import logger


class IdAndSsoConfig(AppConfig):
    name = "idandsso"
    verbose_name = "ID & SSO"

    def ready(self):
        super().ready()

        self._check_required_settings()
        self._check_middleware()
        self._check_idp_availability()

        import idandsso.signals  # noqa F401

    def _check_required_settings(self):
        from idandsso.adapter import KeycloakOrcidAccountAdapter

        qualified_adapter_class_name = ".".join(
            [
                KeycloakOrcidAccountAdapter.__module__,
                KeycloakOrcidAccountAdapter.__name__,
            ]
        )
        configured_account_adapter = getattr(settings, "ACCOUNT_ADAPTER", None)

        if not configured_account_adapter == qualified_adapter_class_name:
            logger.error(
                f"ACCOUNT_ADAPTER='{configured_account_adapter}' != '{qualified_adapter_class_name}'"
            )

        email_verification = getattr(settings, "ACCOUNT_EMAIL_VERIFICATION", "not-correct")
        if email_verification != "none":
            logger.error(f"ACCOUNT_EMAIL_VERIFICATION MUST be `none` and not '{email_verification}")

        for boolean_setting in [
            "SOCIALACCOUNT_ENABLED",
            "SOCIALACCOUNT_EMAIL_REQUIRED",
        ]:
            if not getattr(settings, boolean_setting, False):
                logger.error(f"{boolean_setting} MUST BE TRUE!")

        if not getattr(settings, "SITE_URL", False) and not getattr(settings, "SITEURL", False):
            logger.error("SITE_URL or SITEURL is NOT configured!")

        for configured_setting in [
            "GEONODE_API_TIMEOUT",
            "IDANDSSO_CLIENT_ID",
            "IDANDSSO_CLIENT_SECRET",
            "IDANDSSO_CONNECTOR_NAME",
            "IDANDSSO_GROUP_MAP",
            "IDANDSSO_GROUP_NAME_DJANGO_STAFF",
            "IDANDSSO_GROUP_NAME_DJANGO_SUPERUSER",
            "IDANDSSO_PROVIDER_HOST",
            "IDANDSSO_PROVIDER_ID",
            "IDANDSSO_PROVIDER_REALM",
            "IDANDSSO_PROVIDER_ROOT",
            "LOGIN_REDIRECT_URL",
            "LOGIN_URL",
            "SOCIALACCOUNT_LOGOUT_REDIRECT_URL",
        ]:
            if not getattr(settings, configured_setting, None):
                logger.error(f"{configured_setting} MUST BE CONFIGURED!")

    def _check_middleware(self):
        middleware_stack = getattr(settings, "MIDDLEWARE")
        all_auth_account_middleware = "allauth.account.middleware.AccountMiddleware"
        idandsso_middleware = "idandsso.middleware.KeycloakSilentSSOMiddleware"
        if all_auth_account_middleware not in middleware_stack:
            logger.error("allauth account middleware missing in django middleware stack")
        if idandsso_middleware not in middleware_stack:
            logger.error("idandsso middleware missing in django middleware stack")
        if (
            all_auth_account_middleware in middleware_stack
            and idandsso_middleware in middleware_stack
            and middleware_stack.index(idandsso_middleware)
            > middleware_stack.index(all_auth_account_middleware)
        ):
            logger.error("idandsso middleware MUST be configured BEFORE allauth account middleware")

    def _check_idp_availability(self):
        try:
            import requests

            response = requests.get(
                settings.IDANDSSO_PROVIDER_HOST, timeout=settings.GEONODE_API_TIMEOUT
            )
            if response.status_code != 200:
                raise Exception(
                    f"IDP instance not reachable at '{settings.IDANDSSO_PROVIDER_HOST}'"
                )
        except Exception as e:
            logger.warning(
                f"Error connecting to IDP instance at '{settings.IDANDSSO_PROVIDER_HOST}', configured IDANDSSO_PROVIDER_HOST may be incorrect or IDP not available ..."
            )
            logger.warning(e)
