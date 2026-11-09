"""Account services: phone normalisation and SMS one-time codes (OTP).

Security rules (plan §7, ADR-0004):
- only an HMAC (server secret) of the code is stored;
- 5 attempts per challenge, and a cap on failed attempts per phone across challenges;
- send limits per phone, per IP and a global daily cap (SMS-pumping protection);
- only whitelisted country prefixes (+237 at launch);
- constant-time comparison, single use.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

import phonenumbers
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import Country

from .models import OTPChallenge, User


class OTPError(Exception):
    """Base error. `str(error)` is a message safe to show to the user."""


class InvalidPhone(OTPError):
    pass


class PhoneNotAllowed(OTPError):
    pass


class TooManyRequests(OTPError):
    pass


class InvalidCode(OTPError):
    pass


# --- Phone numbers ---------------------------------------------------------------------------


def normalize_phone(raw: str, region: str | None = None) -> str:
    """Return the E.164 form of a phone number typed by a user, or raise InvalidPhone."""
    region = region or settings.DEFAULT_PHONE_REGION
    try:
        number = phonenumbers.parse((raw or "").strip(), region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhone(_("Ce numéro de téléphone n'est pas valide.")) from exc
    if not phonenumbers.is_valid_number(number):
        raise InvalidPhone(_("Ce numéro de téléphone n'est pas valide."))
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def display_phone(e164: str) -> str:
    try:
        return phonenumbers.format_number(phonenumbers.parse(e164, None), phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except phonenumbers.NumberParseException:
        return e164


def ensure_phone_allowed(e164: str) -> None:
    if not any(e164.startswith(prefix) for prefix in settings.OTP_ALLOWED_PREFIXES):
        raise PhoneNotAllowed(_("Ce service n'est pas encore disponible pour ce pays."))


# --- OTP -------------------------------------------------------------------------------------


def _hmac(phone: str, purpose: str, code: str) -> str:
    message = f"{phone}:{purpose}:{code}".encode()
    return hmac.new(settings.OTP_HMAC_KEY.encode(), message, hashlib.sha256).hexdigest()


def _generate_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.OTP_LENGTH))


def _check_send_limits(phone: str, ip_hash: str) -> None:
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)
    recent = OTPChallenge.objects.filter(created_at__gte=hour_ago)
    if recent.filter(phone=phone).count() >= settings.OTP_MAX_SENDS_PER_PHONE_PER_HOUR:
        raise TooManyRequests(_("Trop de codes demandés pour ce numéro. Réessaie dans une heure."))
    if ip_hash and recent.filter(ip_hash=ip_hash).count() >= settings.OTP_MAX_SENDS_PER_IP_PER_HOUR:
        raise TooManyRequests(_("Trop de demandes depuis cet appareil. Réessaie plus tard."))
    day_start = now - timedelta(hours=24)
    if OTPChallenge.objects.filter(created_at__gte=day_start).count() >= settings.OTP_MAX_SENDS_PER_DAY_GLOBAL:
        # Global spend cap: protects the SMS budget against pumping attacks.
        raise TooManyRequests(_("Le service SMS est momentanément saturé. Réessaie un peu plus tard."))


def request_otp(phone: str, purpose: str, *, ip_hash: str = "") -> OTPChallenge:
    """Create a challenge and schedule the SMS. `phone` must already be E.164."""
    ensure_phone_allowed(phone)
    _check_send_limits(phone, ip_hash)
    code = _generate_code()
    with transaction.atomic():
        # A new code invalidates the previous ones for the same purpose.
        OTPChallenge.objects.filter(phone=phone, purpose=purpose, consumed_at__isnull=True).update(
            consumed_at=timezone.now()
        )
        challenge = OTPChallenge.objects.create(
            phone=phone,
            purpose=purpose,
            code_hmac=_hmac(phone, purpose, code),
            expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
            ip_hash=ip_hash,
        )
        body = _("{site} : ton code est {code}. Il expire dans 5 minutes. Ne le partage avec personne.").format(
            site=settings.SITE_NAME, code=code
        )
        from .tasks import send_sms_task  # local import: avoids a cycle at app loading

        transaction.on_commit(lambda: send_sms_task(phone, body))
    return challenge


def verify_otp(phone: str, purpose: str, code: str) -> None:
    """Consume the current challenge if `code` is right, otherwise raise InvalidCode/TooManyRequests."""
    code = (code or "").strip().replace(" ", "")
    hour_ago = timezone.now() - timedelta(hours=1)
    # The error is decided inside the transaction but raised AFTER it commits: raising inside
    # `atomic()` would roll back the attempt counter and void the brute-force protection.
    error: OTPError | None = None
    with transaction.atomic():
        failed_last_hour = sum(
            OTPChallenge.objects.filter(phone=phone, created_at__gte=hour_ago).values_list("attempts", flat=True)
        )
        challenge = (
            OTPChallenge.objects.select_for_update()
            .filter(phone=phone, purpose=purpose, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if failed_last_hour >= settings.OTP_MAX_ATTEMPTS * 2:
            error = TooManyRequests(_("Trop d'essais. Patiente une heure avant de réessayer."))
        elif challenge is None or challenge.is_expired:
            error = InvalidCode(_("Ce code a expiré. Demande un nouveau code."))
        elif challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
            error = TooManyRequests(_("Trop d'essais pour ce code. Demande un nouveau code."))
        elif not hmac.compare_digest(challenge.code_hmac, _hmac(phone, purpose, code)):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            remaining = max(settings.OTP_MAX_ATTEMPTS - challenge.attempts, 0)
            error = InvalidCode(_("Code incorrect. Il te reste %(n)d essai(s).") % {"n": remaining})
        else:
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["consumed_at"])
    if error is not None:
        raise error


# --- Users -----------------------------------------------------------------------------------


def get_or_create_user(phone: str) -> tuple[User, bool]:
    """Return the account for a *verified* phone, creating it if needed. Never duplicates."""
    country = next((c for c in Country.objects.all() if phone.startswith(c.phone_prefix)), None)
    user = User.objects.filter(phone=phone).first()
    created = user is None
    if created:
        try:
            with transaction.atomic():
                user = User.objects.create_user(phone=phone, country=country)
        except IntegrityError:  # concurrent sign-up with the same phone
            user = User.objects.get(phone=phone)
            created = False
    user.phone_verified_at = timezone.now()
    user.last_seen_at = timezone.now()
    user.save(update_fields=["phone_verified_at", "last_seen_at"])
    return user, created
