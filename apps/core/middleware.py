"""Cross-cutting middleware."""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from .utils import client_ip, rate_key_ip

ADMIN_LOGIN_WINDOW_SECONDS = 60 * 60


class AdminLoginThrottleMiddleware:
    """Brute-force protection of the staff password form (/gestion/login/).

    At most ADMIN_LOGIN_MAX_ATTEMPTS_PER_HOUR POSTs per client IP (IPv6 grouped by /64) per hour.
    The counter is created with cache.add then incremented with cache.incr: both are atomic on
    Redis, so parallel requests cannot slip through. Answers 429 once the limit is reached.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._login_path: str | None = None

    def _admin_login_path(self) -> str:
        if self._login_path is None:
            try:
                self._login_path = reverse("admin:login")
            except NoReverseMatch:  # pragma: no cover - admin not mounted
                self._login_path = ""
        return self._login_path

    def __call__(self, request):
        login_path = self._admin_login_path()
        if request.method == "POST" and login_path and request.path == login_path:
            key = f"admin-login:{rate_key_ip(client_ip(request))}"
            cache.add(key, 0, timeout=ADMIN_LOGIN_WINDOW_SECONDS)
            try:
                attempts = cache.incr(key)
            except ValueError:  # expired between add and incr: start a new window
                cache.add(key, 1, timeout=ADMIN_LOGIN_WINDOW_SECONDS)
                attempts = 1
            if attempts > settings.ADMIN_LOGIN_MAX_ATTEMPTS_PER_HOUR:
                response = render(request, "admin/login_throttled.html", status=429)
                response["Retry-After"] = str(ADMIN_LOGIN_WINDOW_SECONDS)
                response["Cache-Control"] = "no-store"
                return response
        return self.get_response(request)
