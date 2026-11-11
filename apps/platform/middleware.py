"""Maintenance mode: every public request answers a branded 503, staff and infrastructure excepted."""

from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import render

from . import services

logger = logging.getLogger(__name__)

RETRY_AFTER_SECONDS = 600


def _exempt_prefixes() -> tuple[str, ...]:
    prefixes = ["/" + settings.ADMIN_URL.lstrip("/"), "/healthz", "/robots.txt"]
    for url in (settings.STATIC_URL, settings.MEDIA_URL):
        if url and url.startswith("/"):
            prefixes.append(url)
    return tuple(prefixes)


def render_maintenance(request, *, status: int = 503, preview: bool = False):
    response = render(
        request,
        "platform/maintenance.html",
        {"maintenance_message": services.get_settings().maintenance_message, "preview": preview},
        status=status,
    )
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Cache-Control"] = "no-store"
    if status == 503:
        response["Retry-After"] = str(RETRY_AFTER_SECONDS)
    return response


class MaintenanceModeMiddleware:
    """Must sit after AuthenticationMiddleware (staff bypass). One cache read per request."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt = _exempt_prefixes()

    def __call__(self, request):
        if self._blocked(request):
            return render_maintenance(request)
        return self.get_response(request)

    def _blocked(self, request) -> bool:
        try:
            on = services.get_settings().maintenance_mode
        except Exception:  # fail open: a settings/DB failure must not take the whole site down
            logger.debug("maintenance check skipped", exc_info=True)
            return False
        if not on or request.path.startswith(self.exempt):
            return False
        user = getattr(request, "user", None)
        return not (user is not None and user.is_authenticated and user.is_staff)
