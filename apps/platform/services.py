"""Read access to platform switches. Every app checks features through this module only.

from apps.platform.services import feature, get_settings
if not feature("card_activation"): ...
"""

from __future__ import annotations

from django.core.cache import cache

from .models import AuditLog, BlockedPhone, SiteSettings

CACHE_KEY = "platform:settings:v1"
CACHE_TTL = 30  # seconds: a toggle in the admin applies everywhere within 30 s (immediately on this process)

FEATURES = {
    "signups": "signups_enabled",
    "login": "login_enabled",
    "card_activation": "card_activation_enabled",
    "page_creation": "page_creation_enabled",
    "themes": "themes_enabled",
    "directory": "directory_enabled",
    "reports": "reports_enabled",
    "indexing": "indexing_notifications_enabled",
    "instant_publish": "instant_publish_enabled",
    "maintenance": "maintenance_mode",
    "otp_whatsapp": "otp_whatsapp_enabled",
    "otp_firebase_sms": "otp_firebase_sms_enabled",
    "otp_sms_gateway": "otp_sms_gateway_enabled",
}


def get_settings() -> SiteSettings:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    obj, _ = SiteSettings.objects.get_or_create(pk=1)
    cache.set(CACHE_KEY, obj, CACHE_TTL)
    return obj


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def feature(name: str) -> bool:
    """True if the named feature is enabled. Unknown names raise KeyError (typos must fail loudly)."""
    return bool(getattr(get_settings(), FEATURES[name]))


def enabled_otp_channels() -> list[str]:
    """Channels switched on in the admin, default channel first (configuration checked by accounts)."""
    s = get_settings()
    channels = [
        code
        for code, on in (
            (SiteSettings.OtpChannel.WHATSAPP, s.otp_whatsapp_enabled),
            (SiteSettings.OtpChannel.FIREBASE_SMS, s.otp_firebase_sms_enabled),
            (SiteSettings.OtpChannel.SMS_GATEWAY, s.otp_sms_gateway_enabled),
        )
        if on
    ]
    channels.sort(key=lambda c: c != s.otp_default_channel)
    return [str(c) for c in channels]


def is_phone_blocked(phone: str) -> bool:
    return BlockedPhone.objects.filter(phone=phone).exists()


def audit(actor, action: str, target: str = "", **details) -> None:
    AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None, action=action, target=target[:200], details=details
    )
