"""Read access to platform switches. Every app checks features through this module only.

from apps.platform.services import feature, get_settings
if not feature("card_activation"): ...
"""

from __future__ import annotations

import time
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

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


# --- Account management (admin actions) ------------------------------------------------------


def terminate_sessions(user) -> int:
    """Delete every server-side session of `user` ("déconnecter de tous les appareils").

    Works with the database-backed session engines (db, cached_db). Returns the number deleted.
    """
    from django.contrib.sessions.models import Session

    user_id = str(user.pk)
    doomed = [
        session.session_key
        for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator()
        if str(session.get_decoded().get("_auth_user_id", "")) == user_id
    ]
    if not doomed:
        return 0

    store = import_module(settings.SESSION_ENGINE).SessionStore
    for key in doomed:
        store(session_key=key).delete()  # also clears the cache copy for cached_db
    Session.objects.filter(session_key__in=doomed).delete()
    return len(doomed)


def set_user_active(user, active: bool, *, actor=None) -> bool:
    """Activate or deactivate an account. Deactivation also logs it out everywhere.

    Returns True when the flag changed.
    """
    changed = user.is_active != active
    if changed:
        type(user).objects.filter(pk=user.pk).update(is_active=active)
        user.is_active = active
    sessions = 0 if active else terminate_sessions(user)
    if changed or sessions:
        audit(actor, "user.activate" if active else "user.deactivate", user.phone, sessions=sessions)
    return changed


def logout_everywhere(user, *, actor=None) -> int:
    count = terminate_sessions(user)
    audit(actor, "user.logout_everywhere", user.phone, sessions=count)
    return count


def block_phone(phone: str, *, reason: str, actor=None) -> BlockedPhone:
    """Refuse this number at login/sign-up, deactivate its account and log it out everywhere."""

    blocked, created = BlockedPhone.objects.get_or_create(
        phone=phone, defaults={"reason": reason[:200], "created_by": actor if getattr(actor, "pk", None) else None}
    )
    if created:
        audit(actor, "phone.block", phone, reason=reason[:200])
    for user in get_user_model().objects.filter(phone=phone):
        set_user_active(user, False, actor=actor)
    return blocked


def unblock_phone(phone: str, *, actor=None, reactivate: bool = True) -> bool:
    """Lift the block. With `reactivate`, the matching account can log in again."""

    deleted, _ = BlockedPhone.objects.filter(phone=phone).delete()
    if deleted:
        audit(actor, "phone.unblock", phone)
    if reactivate:
        for user in get_user_model().objects.filter(phone=phone):
            set_user_active(user, True, actor=actor)
    return bool(deleted)


# --- Control center --------------------------------------------------------------------------


def update_settings(actor, section: str, values: dict) -> dict:
    """Apply `values` (field -> new value) to the singleton, audit the diff and invalidate the cache.

    Returns {field: [old, new]} for the fields that actually changed (empty dict: nothing saved).
    """
    obj, _ = SiteSettings.objects.get_or_create(pk=1)
    changes = {}
    for field, new in values.items():
        old = getattr(obj, field)
        if old != new:
            changes[field] = [old, new]
            setattr(obj, field, new)
    if changes:
        obj.updated_by = actor if getattr(actor, "pk", None) else None
        obj.save()  # SiteSettings.save() invalidates the cache
        audit(actor, "settings.update", section, changes={k: [str(o), str(n)] for k, (o, n) in changes.items()})
    return changes


HEARTBEAT_KEY = "platform:huey:heartbeat"
HEARTBEAT_LATE_SECONDS = 3 * 60


def record_heartbeat() -> float:

    now = time.time()
    cache.set(HEARTBEAT_KEY, now, 24 * 60 * 60)
    return now


def heartbeat_age() -> float | None:
    """Seconds since the Huey worker last ran its heartbeat task (None: never seen)."""

    value = cache.get(HEARTBEAT_KEY)
    return None if value is None else max(0.0, time.time() - float(value))
