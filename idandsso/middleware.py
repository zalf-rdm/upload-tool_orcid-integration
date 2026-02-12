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

from django.conf import settings
from loguru import logger

from .utils import sso_cookie_domain


class KeycloakSilentSSOMiddleware:
    """
    configure using upload_manager.middleware.KeycloakSilentSSOMiddleware
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            request.method == "POST"
            and "/accounts/logout/" in request.path
            and request.COOKIES.get("sso_hint") == "true"
        ):
            logger.debug("deleting cookie")
            response.delete_cookie("sso_hint", domain=sso_cookie_domain(), path="/")

        elif request.user.is_authenticated:
            sso_cookie_max_age = getattr(settings, "SESSION_COOKIE_AGE", 3600)

            if "text/html" in request.META.get("HTTP_ACCEPT", ""):
                logger.debug("refreshing sso_hint cookie")
                response.set_cookie(
                    "sso_hint",
                    "true",
                    domain=sso_cookie_domain(),
                    max_age=sso_cookie_max_age,
                    samesite="Lax",
                    path="/",
                    secure=request.is_secure(),
                    httponly=False,
                )

        return response
