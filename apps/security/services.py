"""Two-factor authentication (TOTP) of every staff account on the admin (ADR-0010).

Flow: admin password login -> no confirmed TOTP device: forced enrollment (QR code, confirmation
code, 10 single-use backup codes shown once) -> otherwise verification (TOTP or backup code).
Until the session is verified, apps.core.middleware.StaffTwoFactorMiddleware redirects every admin
URL here, and admin.site.has_permission refuses access (defense in depth, see admin.py).

Devices are django-otp models (otp_totp, otp_static): replays are refused by TOTPDevice.last_t,
and each device has its own exponential throttling on top of our per (user, IP) attempt limit.
"""

from __future__ import annotations

import base64
import time
from urllib.parse import urlencode

import segno
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.utils import client_ip, rate_key_ip, security_ip_hash
from apps.platform import services as platform

TOTP_DEVICE_NAME = "application"
BACKUP_DEVICE_NAME = "codes-de-secours"
BACKUP_CODES_COUNT = 10
BACKUP_CODES_SESSION_KEY = "security_2fa_backup_codes"
BACKUP_CODES_DISPLAY_SECONDS = 15 * 60  # the plain codes stay in the session at most 15 minutes

OK, OK_BACKUP, INVALID, LOCKED = "ok", "ok_backup", "invalid", "locked"


# --- State ---------------------------------------------------------------------------------------


def is_required(user) -> bool:
    """2FA applies to every active staff account (superusers included) when STAFF_2FA_REQUIRED."""
    return bool(
        settings.STAFF_2FA_REQUIRED
        and getattr(user, "is_authenticated", False)
        and user.is_active
        and (user.is_staff or user.is_superuser)
    )


def is_verified(user) -> bool:
    """True if this session passed 2FA. Fails closed if OTPMiddleware is missing."""
    check = getattr(user, "is_verified", None)
    return bool(check and check())


def needs_two_factor(user) -> bool:
    return is_required(user) and not is_verified(user)


def has_confirmed_device(user) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def remaining_backup_codes(user) -> int:
    return StaticToken.objects.filter(device__user=user, device__confirmed=True).count()


def admin_prefix() -> str:
    return "/" + settings.ADMIN_URL.lstrip("/")


def safe_next(request, default: str = "") -> str:
    """The `next` target if it is a local admin URL, otherwise the admin index."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    if (
        target
        and target.startswith(admin_prefix())
        and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=False)
    ):
        return target
    return default or reverse("admin:index")


def redirect_to_two_factor(request):
    """Redirect an unverified staff member to enrollment (no device yet) or verification."""
    name = "admin:security_2fa_verify" if has_confirmed_device(request.user) else "admin:security_2fa_enroll"
    login_path = reverse("admin:login")
    target = request.get_full_path() if request.method == "GET" and request.path != login_path else ""
    if not target and request.path == login_path:
        target = request.GET.get("next", "")
    url = reverse(name)
    if target and target.startswith(admin_prefix()):
        url += "?" + urlencode({"next": target})
    return redirect(url)


# --- Enrollment ----------------------------------------------------------------------------------


def pending_device(user) -> TOTPDevice:
    """The unconfirmed TOTP device being enrolled: the same secret across page reloads."""
    device = TOTPDevice.objects.filter(user=user, confirmed=False).order_by("-pk").first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name=TOTP_DEVICE_NAME, confirmed=False)
    return device


def qr_svg(device: TOTPDevice) -> str:
    """The otpauth:// URI as an inline SVG QR code (segno, generated here: no external service).

    Presentation attributes only (fill/stroke), no style attribute: compatible with the strict CSP.
    """
    qr = segno.make(device.config_url, error="m")
    return qr.svg_inline(
        scale=5, border=3, dark="#000", light="#fff", svgclass="mx-2fa-qr__svg", title="QR code (TOTP)"
    )


def manual_secret(device: TOTPDevice) -> str:
    """Base32 secret in groups of 4 characters, for apps that cannot scan."""
    raw = base64.b32encode(device.bin_key).decode().rstrip("=")
    return " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def confirm_enrollment(request, device: TOTPDevice, raw_token: str) -> list[str] | None:
    """Confirm the pending device with a code from the app. Returns the new backup codes, or None.

    Never raises after the attempt counters moved (ATOMIC_REQUESTS would roll them back).
    """
    user = request.user
    token = normalize_token(raw_token)
    if not (token.isdigit() and len(token) == device.digits and device.verify_token(token)):
        platform.audit(user, "2fa.verify_failed", user.phone, stage="enroll", ip=security_ip_hash(request))
        return None
    device.confirmed = True
    device.save(update_fields=["confirmed"])
    TOTPDevice.objects.filter(user=user).exclude(pk=device.pk).delete()
    _, codes = regenerate_backup_codes(user)
    complete_verification(request, device)
    platform.audit(user, "2fa.enroll", user.phone, ip=security_ip_hash(request))
    return codes


def regenerate_backup_codes(user) -> tuple[StaticDevice, list[str]]:
    """Replace every backup code of `user` by BACKUP_CODES_COUNT new single-use codes."""
    StaticDevice.objects.filter(user=user).delete()
    device = StaticDevice.objects.create(user=user, name=BACKUP_DEVICE_NAME, confirmed=True)
    codes: set[str] = set()
    while len(codes) < BACKUP_CODES_COUNT:
        codes.add(StaticToken.random_token())
    ordered = sorted(codes)
    StaticToken.objects.bulk_create(StaticToken(device=device, token=code) for code in ordered)
    return device, ordered


def regenerate_backup_codes_for_session(request) -> list[str]:
    """Regenerate from a verified session; keep it verified if it was verified by a backup code."""
    user = request.user
    was_backup = isinstance(getattr(user, "otp_device", None), StaticDevice)
    device, codes = regenerate_backup_codes(user)
    if was_backup:
        otp_login(request, device)
    platform.audit(user, "2fa.backup_codes_regenerated", user.phone, ip=security_ip_hash(request))
    return codes


def format_backup_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}" if len(code) == 8 else code


# --- Verification --------------------------------------------------------------------------------


def normalize_token(raw: str | None) -> str:
    """Keep letters and digits only (users type "123 456" or "abcd-efgh"), lower-cased."""
    return "".join(ch for ch in (raw or "")[:64] if ch.isascii() and ch.isalnum()).lower()


def _attempts_key(user, request) -> str:
    return f"2fa-attempts:{user.pk}:{rate_key_ip(client_ip(request))}"


def register_attempt(request) -> bool:
    """Reserve one attempt for (user, IP), atomically (cache.add + cache.incr are atomic on Redis).

    Returns False once STAFF_2FA_MAX_ATTEMPTS attempts were made in the window: the caller must
    refuse WITHOUT checking the code. The first refused attempt is audited.
    """
    key = _attempts_key(request.user, request)
    window = settings.STAFF_2FA_WINDOW_SECONDS
    cache.add(key, 0, timeout=window)
    try:
        attempts = cache.incr(key)
    except ValueError:  # expired between add and incr: start a new window
        cache.add(key, 1, timeout=window)
        attempts = 1
    if attempts == settings.STAFF_2FA_MAX_ATTEMPTS + 1:
        platform.audit(request.user, "2fa.locked", request.user.phone, ip=security_ip_hash(request))
    return attempts <= settings.STAFF_2FA_MAX_ATTEMPTS


def complete_verification(request, device) -> None:
    """Mark the session as verified by `device`, then rotate the session key (fixation)."""
    otp_login(request, device)
    request.session.cycle_key()
    cache.delete(_attempts_key(request.user, request))


def verify(request, raw_token: str) -> str:
    """Check a TOTP code (6 digits) or a backup code (8 characters). Returns OK/OK_BACKUP/INVALID/LOCKED."""
    user = request.user
    if not register_attempt(request):
        return LOCKED
    token = normalize_token(raw_token)
    matched = None
    if token.isdigit() and len(token) == 6:
        for device in TOTPDevice.objects.filter(user=user, confirmed=True):
            if device.verify_token(token):  # refuses replays (last_t) and throttles per device
                matched = device
                break
    elif len(token) == 8:
        for device in StaticDevice.objects.filter(user=user, confirmed=True):
            if device.verify_token(token):  # deletes the code: single use
                matched = device
                break
    if matched is None:
        platform.audit(user, "2fa.verify_failed", user.phone, stage="verify", ip=security_ip_hash(request))
        return INVALID
    complete_verification(request, matched)
    if isinstance(matched, StaticDevice):
        platform.audit(
            user,
            "2fa.backup_code_used",
            user.phone,
            remaining=remaining_backup_codes(user),
            ip=security_ip_hash(request),
        )
        return OK_BACKUP
    return OK


# --- Backup codes shown once ---------------------------------------------------------------------


def stash_backup_codes(request, codes: list[str]) -> None:
    request.session[BACKUP_CODES_SESSION_KEY] = {"codes": codes, "at": int(time.time())}


def stashed_backup_codes(request) -> list[str]:
    data = request.session.get(BACKUP_CODES_SESSION_KEY) or {}
    if not data or time.time() - data.get("at", 0) > BACKUP_CODES_DISPLAY_SECONDS:
        request.session.pop(BACKUP_CODES_SESSION_KEY, None)
        return []
    return list(data.get("codes", []))


def forget_backup_codes(request) -> None:
    request.session.pop(BACKUP_CODES_SESSION_KEY, None)


# --- Superuser tools -----------------------------------------------------------------------------


def reset_two_factor(user, *, actor) -> int:
    """Delete every 2FA device of `user` (lost phone): next login forces a new enrollment.

    Superusers only, never on their own account. Every session of `user` is closed, so a stolen
    session cannot enroll a device of its own. Returns the number of devices deleted.
    """
    if actor is None or not actor.is_superuser or actor.pk == user.pk:
        raise PermissionDenied
    count = TOTPDevice.objects.filter(user=user).count() + StaticDevice.objects.filter(user=user).count()
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
    platform.terminate_sessions(user)
    platform.audit(actor, "2fa.reset", user.phone, devices=count)
    return count


def two_factor_summary() -> dict:
    """Control-center data: how many active staff accounts have 2FA, and who does not yet.

    {"required": bool, "staff_total": int, "staff_enrolled": int,
     "staff_without_2fa": [{"id", "phone", "full_name", "is_superuser", "last_login", "date_joined"}]}
    """
    User = get_user_model()
    staff = User.objects.filter(is_active=True, is_staff=True)
    enrolled = set(
        TOTPDevice.objects.filter(confirmed=True, user__in=staff).values_list("user_id", flat=True).distinct()
    )
    without = [
        {
            "id": u.pk,
            "phone": u.phone,
            "full_name": u.full_name,
            "is_superuser": u.is_superuser,
            "last_login": u.last_login,
            "date_joined": u.date_joined,
        }
        for u in staff.exclude(pk__in=enrolled).order_by("phone")
    ]
    return {
        "required": bool(settings.STAFF_2FA_REQUIRED),
        "staff_total": staff.count(),
        "staff_enrolled": len(enrolled),
        "staff_without_2fa": without,
    }


def forget_session_verification(request) -> None:
    """Drop the 2FA mark of a session (used on every staff password login)."""
    if hasattr(request, "session"):
        request.session.pop(DEVICE_ID_SESSION_KEY, None)
