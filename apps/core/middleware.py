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


class StaffTwoFactorMiddleware:
    """Staff must pass TOTP two-factor authentication before reaching ANY admin URL (ADR-0010).

    Sits after OTPMiddleware (request.user.is_verified). For an authenticated, active staff member
    whose session is not verified, every URL under settings.ADMIN_URL (models, control center,
    jsi18n…) redirects to enrollment (no device yet) or verification. Only the 2FA pages, the
    logout and the password form submission stay reachable. admin.site.has_permission repeats
    the check (apps.security.admin), so removing this middleware never opens the admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.prefix = "/" + settings.ADMIN_URL.lstrip("/")
        self._open_paths: frozenset[str] | None = None

    def _open(self) -> frozenset[str]:
        if self._open_paths is None:
            self._open_paths = frozenset(
                reverse(name) for name in ("admin:security_2fa_enroll", "admin:security_2fa_verify", "admin:logout")
            )
        return self._open_paths

    def __call__(self, request):
        if settings.STAFF_2FA_REQUIRED and request.path.startswith(self.prefix):
            from apps.security import services  # lazy: apps are loaded after middleware import

            user = getattr(request, "user", None)
            if user is not None and services.needs_two_factor(user) and not self._allowed(request):
                return services.redirect_to_two_factor(request)
        return self.get_response(request)

    def _allowed(self, request) -> bool:
        if request.path in self._open():
            return True
        # Re-submitting the password form (switching account) stays possible; a GET goes to 2FA.
        return request.method == "POST" and request.path == self._admin_login_path()

    @staticmethod
    def _admin_login_path() -> str:
        return reverse("admin:login")
