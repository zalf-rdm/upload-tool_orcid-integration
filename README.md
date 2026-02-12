# ID and SSO

ID & SSO enables single sign on incl. IDP integration.
The provided features are:

* automatic login if login in another linked app happened beforehand.
* synchronize group membership between django and IDP.

## Installation

Add this repository as dependency to your application.
Use the following, if using a pyproject.toml:

```python
dependencies = [
    [...]
    "idandsso@git+https://github.com/GeoNodeUserGroup-DE/geonode-orcid-adapter",
]
```

## Environment Variables

The following environment variables are supported:

* `DJANGO_IDANDSSO_CLIENT_ID` **mandatory**
* `DJANGO_IDANDSSO_SECRET_KEY` **mandatory**
* `DJANGO_IDANDSSO_CONNECTOR_NAME`
* `DJANGO_IDANDSSO_GROUP_MAP`
* `DJANGO_IDANDSSO_GROUP_NAME_DJANGO_STAFF`
* `DJANGO_IDANDSSO_GROUP_NAME_DJANGO_SUPERUSER`
* `DJANGO_IDANDSSO_PROVIDER_HOST`
* `DJANGO_IDANDSSO_PROVIDER_ID`
* `DJANGO_IDANDSSO_PROVIDER_REALM`

Check the following `settings.py` snippets for more details about the usage and allowed values.

## Settings

Add the ID & SSO app to your `settings.py` by adding `idandsso` to `INSTALLED_APPS` **before** the app, you want to use it in and before the `allauth*` apps.
The required allauth apps are:

* `allauth`,
* `allauth.account`,
* `allauth.socialaccount`,
* `allauth.socialaccount.providers.openid_connect`

```python
INSTALLED_APPS = [
    #
    #
    "idandsso",
    "upload_manager",
    "submission",
    "upload_celery",
    #
    #
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    [...]
```

Configure the `MIDDLEWARE` and ensure that `idandsso.middleware.KeycloakSilentSSOMiddleware` is listed before `allauth.*`:

```python
MIDDLEWARE = [
    [...]
    "idandsso.middleware.KeycloakSilentSSOMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    [...]
]
```

Ensure the `TEMPLATES` are not using `DIRS`, but `APP_DIRS`:

```python
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    },
]
```

`ACCOUNT_` settings:

```shell
ACCOUNT_ADAPTER = "idandsso.adapter.KeycloakOrcidAccountAdapter"
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_LOGOUT_REDIRECT_URL = urljoin(SITE_URL, "/")
# Force HTTPS protocol for OAuth callbacks in production only
# See: https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http" if DEBUG else "https"
```

`SOCIALACCOUNT_*` settings:

```python
#
# see https://docs.allauth.org/en/latest/socialaccount/configuration.html
#
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_ENABLED = True
#
# This logs the user from ORCID out, too. The "problem" is that we cannot provide
# an redirect back to the upload tool atm
#
#   ORCID SANDBOX LOGOUT
#
SOCIALACCOUNT_LOGOUT_REDIRECT_URL = "https://sandbox.orcid.org/signout"
#
#   ORCID PRODUCTION LOGOUT
#
# SOCIALACCOUNT_LOGOUT_REDIRECT_URL = "https://orcid.org/signout"
#
#   This skips the logout from ORCID, hence clicking on login after logout
#   restarts a new session without any further request for credentials
#   depending on the session lifetime in keycloak/ORCID.
#
# SOCIALACCOUNT_LOGOUT_REDIRECT_URL = LOGIN_REDIRECT_URL
#
# When enabled (True), all functionality with regard to local accounts is disabled,
# and users will only be able to authenticate using third-party providers.
#
SOCIALACCOUNT_ONLY = False
```

`IDANDSSO` settings incl. `SOCIALACCOUNT_PROVIDERS`:

```python
#
#   Used internally to reference the configuration of allauth
#
IDANDSSO_PROVIDER_ID = os.environ.get("DJANGO_IDANDSSO_PROVIDER_ID", "zalf-idp")
#
#   Used as name of the configuration
#
IDANDSSO_CONNECTOR_NAME = os.environ.get("DJANGO_IDANDSSO_CONNECTOR_NAME", "ORCID")
#
#   MUST match keycloak configuration
#
IDANDSSO_PROVIDER_REALM = os.environ.get("DJANGO_IDANDSSO_PROVIDER_REALM", "ORCID")
#
#   protocol, hostname and port required to access the keycloak instance
#
IDANDSSO_PROVIDER_HOST = os.environ.get(
    "DJANGO_IDANDSSO_PROVIDER_HOST", "https://host.docker.internal:8008/"
)
IDANDSSO_PROVIDER_ROOT = f"{IDANDSSO_PROVIDER_HOST}realms/{IDANDSSO_PROVIDER_REALM}/"
#
#   client id
#
IDANDSSO_CLIENT_ID = os.environ.get("DJANGO_IDANDSSO_CLIENT_ID")
if not IDANDSSO_CLIENT_ID:
    logger.error("DJANGO_IDANDSSO_CLIENT_ID not set in environment")
#
#   client secret
#
IDANDSSO_CLIENT_SECRET = os.environ.get("DJANGO_IDANDSSO_SECRET_KEY")
if not IDANDSSO_CLIENT_SECRET:
    logger.error("DJANGO_IDANDSSO_SECRET_KEY not set in environment")

SOCIALACCOUNT_PROVIDERS = {
    #
    # We use openid_connect, hence all services use ZALF's keycloak instance, which
    # connects to ORCID or else
    #
    # see https://docs.allauth.org/en/latest/socialaccount/providers/openid_connect.html
    #
    "openid_connect": {
        # Optional PKCE defaults to False, but may be required by your provider
        # Can be set globally, or per app (settings).
        "OAUTH_PKCE_ENABLED": True,
        "APPS": [
            {
                "provider_id": IDANDSSO_PROVIDER_ID,
                "name": IDANDSSO_CONNECTOR_NAME,
                "client_id": IDANDSSO_CLIENT_ID,
                "secret": IDANDSSO_CLIENT_SECRET,
                "settings": {
                    "server_url": urljoin(
                        IDANDSSO_PROVIDER_ROOT, ".well-known/openid-configuration"
                    ),
                    #
                    #   upload tool internal settings
                    #
                    "oidc_endpoint": urljoin(IDANDSSO_PROVIDER_ROOT, "protocol/openid-connect/"),
                },
            },
        ],
    }
}
#
#   This maps the groups from IDP to UT local group names, if required.
#   All NOT mapped groups are skipped, hence ignored.
#
IDANDSSO_GROUP_MAP = {
    "ut_users": "users",
    "ut_data_stewards": "data_stewards",
    "ut_admin": "admin",
}
# Allow IDANDSSO_GROUP_MAP to be overridden by an environment variable (JSON string)
# export DJANGO_IDANDSSO_GROUP_MAP= '{"ut_users": "users", "ut_data_stewards": "data_stewards", "ut_admin": "admin"}'
env_group_map = os.environ.get("DJANGO_IDANDSSO_GROUP_MAP")
if env_group_map:
    try:
        IDANDSSO_GROUP_MAP = json.loads(env_group_map)
    except json.JSONDecodeError as e:
        logger.error(
            f"Could not parse DJANGO_IDANDSSO_GROUP_MAP env var: {e}. Using default."
        )
#
# Configure the name of the group in the IDP, that enables django staff status for its members
#
IDANDSSO_GROUP_NAME_DJANGO_STAFF = os.environ.get(
    "DJANGO_IDANDSSO_GROUP_NAME_DJANGO_STAFF", "ut_django_staff"
)
#
# Configure the name of the group in the IDP, that enables django superuser status for its members
#
IDANDSSO_GROUP_NAME_DJANGO_SUPERUSER = os.environ.get(
    "DJANGO_IDANDSSO_GROUP_NAME_DJANGO_SUPERUSER", "ut_django_superuser"
)
```

Other used settings:

* `SITE_URL|SITEURL` - used to identify the domain for the SSO cookie.
* `GEONODE_API_TIMEOUT` - used during IDP availability tests.

## Templates

Some features provided require certain templates and blocks.

* [`base.html`](./idandsso/templates/base.html):

  This template extends an `additional_scripts` block.
  It adds a loading spinner and java script, if the user it not authenticated.

* [`account/logout.html`](./idandsso/templates/account/logout.html):

  This template overrides allauth's default logout `content` block.
  It uses a white placeholder image [`static/img/bg_login.png`](./idandsso/static/img/bg_login.png) (width: 463px; height: 629px), that should be replaced by something more appealing.

* [`nav.html`](./idandsso/templates/nav.html):

  This template overrides two blocks:
  * `username`: `<li>` element to be displayed in a HTML list in an navigation context.
    It displays the `user.username` field with added ORCID logo and an `<span>` with title `{{ user.first_name }} {{user.last_name }}`.
  * `navigation_login`: `<li>` element providing a one-click login button and an additional local login element if `DEBUG` is enabled.

## Translations

Currently, only English and German translations are provided.

## Additional Content

This work includes graphics from ORCID:

* ORCID following <https://info.orcid.org/documentation/integration-guide/orcid-id-display-guidelines/>
* Downloaded from <https://orcid.filecamp.com/s/o/LdPTOOrMoSrjElD5/VU19wHSMUnX9TD4R>
* Located in [`idandsso/static/img/`](./idandsso/static/img/)

## License

The work is licensed under GPLv3, see [LICENSE](./LICENSE.txt).

## Funding

This work is funded by

| Logo                                                                       | Funding Organization                                                       |
|----------------------------------------------------------------------------|----------------------------------------------------------------------------|
| ![ZALF Logo](https://www.zalf.de/_layouts/15/images/zalfweb/logo_zalf.png) | [Leibniz Centre for Agricultural Landscape Research](https://www.zalf.de/) |
