"""Mount the staff 2FA pages on the admin site and lock the admin until 2FA (ADR-0010).

- URLs: <ADMIN_URL>securite/2fa/… (names "admin:security_2fa_*"), added through admin.site.get_urls
  like the control center (apps.platform.admin).
- Defense in depth: admin.site.has_permission also refuses an unverified staff session, so even
  without StaffTwoFactorMiddleware no admin view (models, control center, jsi18n…) would answer.
- The django-otp device admins are removed: TOTP secrets and backup codes are never shown there.
"""

from __future__ import annotations

from django.contrib import admin
from django.urls import path, reverse
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import services, views


def _security_urls():
    return [
        path("securite/2fa/", views.overview, name="security_2fa_overview"),
        path("securite/2fa/activer/", views.enroll, name="security_2fa_enroll"),
        path("securite/2fa/verifier/", views.verify, name="security_2fa_verify"),
        path("securite/2fa/codes-de-secours/", views.backup_codes, name="security_2fa_backup_codes"),
        path(
            "securite/2fa/codes-de-secours.txt",
            views.backup_codes_download,
            name="security_2fa_backup_codes_download",
        ),
        path(
            "securite/2fa/codes-de-secours/regenerer/",
            views.backup_codes_regenerate,
            name="security_2fa_backup_codes_regenerate",
        ),
    ]


if not getattr(admin.site, "_security_2fa_installed", False):
    _base_get_urls = admin.site.get_urls
    _base_has_permission = admin.site.has_permission

    def _get_urls():
        return _security_urls() + _base_get_urls()

    def _has_permission(request):
        if not _base_has_permission(request):
            return False
        if request.path == reverse("admin:logout"):  # an unverified session must still be able to log out
            return True
        return not services.needs_two_factor(request.user)

    admin.site.get_urls = _get_urls
    admin.site.has_permission = _has_permission
    admin.site._security_2fa_installed = True


for _model in (TOTPDevice, StaticDevice):
    if admin.site.is_registered(_model):
        admin.site.unregister(_model)
