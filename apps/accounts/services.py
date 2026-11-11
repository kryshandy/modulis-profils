"""Account services: phone normalisation and one-time codes (OTP) by WhatsApp or SMS.

Security rules (plan §7, ADR-0004, ADR-0009), identical for every channel:
- only an HMAC (server secret) of the code is stored;
- 5 attempts per challenge, and a cap on failed attempts per phone across challenges;
- send limits per phone, per IP and a global daily cap (SMS-pumping protection);
- only whitelisted country prefixes (+237 at launch);
- staff, disabled and blocked numbers refused before anything is sent;
- platform switches (login, sign-ups, each channel) applied before anything is sent;
- constant-time comparison, single use.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

import phonenumbers
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import Country
from apps.platform import services as platform

from . import otp
from .models import OTPChallenge, User
from .otp.firebase import FirebaseSmsChannel, InvalidFirebaseToken, verify_id_token


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


class AccountNotAllowed(OTPError):
    pass


class ChannelUnavailable(OTPError):
    pass


class SignupsClosed(OTPError):
    pass


class LoginDisabled(OTPError):
    pass


DELIVERY_FAILED_KEY = "otp-delivery-failed:{pk}"
DELIVERY_FAILED_TTL = 15 * 60
# The clear code never travels through the task queue: it waits in the cache under a random key.
OTP_CODE_KEY = "otp-code:{ref}"
FIREBASE_USED_KEY = "firebase-auth-used:{digest}"


def _msg_account_not_allowed() -> str:
    return _("Ce compte ne peut pas se connecter avec un code. Contacte le support Modulis.")


def _msg_blocked() -> str:
    # Generic on purpose: never tell an abuser that the number is on a block list.
    return _("Impossible d'utiliser ce numéro pour le moment. Contacte le support Modulis.")


def _msg_signups_closed() -> str:
    return _("Les inscriptions sont momentanément fermées. Réessaie plus tard.")


def _msg_login_disabled() -> str:
    return _("La connexion est momentanément indisponible. Réessaie un peu plus tard.")


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


# --- Access rules (every channel) -----------------------------------------------------------


def ensure_sms_login_allowed(phone: str) -> None:
    """Staff and disabled accounts can never authenticate with a code (security audit B1).

    Staff use /gestion/ with a password: a one-time code (SIM swap, recycled number, provider
    console) must never grant admin access. Checked BEFORE any code is sent.
    """
    user = User.objects.filter(phone=phone).only("is_staff", "is_superuser", "is_active").first()
    if user and (user.is_staff or user.is_superuser or not user.is_active):
        raise AccountNotAllowed(_msg_account_not_allowed())


def ensure_access_allowed(phone: str) -> None:
    """Platform switches + block list + account state. Same rules for every channel."""
    if not platform.feature("login"):
        raise LoginDisabled(_msg_login_disabled())
    if platform.is_phone_blocked(phone):
        raise AccountNotAllowed(_msg_blocked())
    ensure_sms_login_allowed(phone)
    if not platform.feature("signups") and not User.objects.filter(phone=phone).exists():
        raise SignupsClosed(_msg_signups_closed())


def resolve_channel(code: str | None = None) -> otp.OTPChannel:
    """The channel to use: `code` if available now, else the default one. Raises ChannelUnavailable."""
    channels = otp.available_channels()
    if not channels:
        raise ChannelUnavailable(_("L'envoi de codes est momentanément indisponible. Réessaie plus tard."))
    if not code:
        return channels[0]
    for channel in channels:
        if channel.code == code:
            return channel
    raise ChannelUnavailable(_("Ce moyen de recevoir le code n'est pas disponible. Choisis-en un autre."))


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
        # Global spend cap: protects the SMS/WhatsApp budget against pumping attacks.
        raise TooManyRequests(_("Le service d'envoi de codes est momentanément saturé. Réessaie un peu plus tard."))


def request_otp(phone: str, purpose: str, *, ip_hash: str = "", channel: str | None = None) -> OTPChallenge:
    """Check every rule, create a challenge and schedule the send. `phone` must already be E.164.

    `channel` is a channel code (None = default available channel). For a client-side channel
    (Firebase) nothing is sent by us: the challenge only authorises the browser flow.
    """
    ensure_phone_allowed(phone)
    ensure_access_allowed(phone)
    selected = resolve_channel(channel)
    # Per-phone lock: count-then-insert is racy (parallel POSTs would all pass the limit check).
    lock_key = f"otp-send-lock:{phone}"
    if not cache.add(lock_key, 1, timeout=5):
        raise TooManyRequests(_("Un code est déjà en cours d'envoi. Patiente quelques secondes."))
    try:
        return _create_challenge(phone, purpose, ip_hash, selected)
    finally:
        cache.delete(lock_key)


def _create_challenge(phone: str, purpose: str, ip_hash: str, channel: otp.OTPChannel) -> OTPChallenge:
    _check_send_limits(phone, ip_hash)
    client_side = channel.kind == otp.CLIENT
    code = "" if client_side else _generate_code()
    ttl = settings.FIREBASE_PENDING_TTL_SECONDS if client_side else settings.OTP_TTL_SECONDS
    with transaction.atomic():
        # A new code invalidates the previous ones for the same purpose.
        OTPChallenge.objects.filter(phone=phone, purpose=purpose, consumed_at__isnull=True).update(
            consumed_at=timezone.now()
        )
        challenge = OTPChallenge.objects.create(
            phone=phone,
            purpose=purpose,
            code_hmac="" if client_side else _hmac(phone, purpose, code),
            expires_at=timezone.now() + timedelta(seconds=ttl),
            ip_hash=ip_hash,
            channel=channel.code,
        )
        if not client_side:
            from .tasks import send_otp_task  # local import: avoids a cycle at app loading

            pk, channel_code = challenge.pk, channel.code

            def _enqueue():
                ref = secrets.token_urlsafe(24)
                cache.set(OTP_CODE_KEY.format(ref=ref), code, settings.OTP_TTL_SECONDS)
                send_otp_task(channel_code, phone, ref, pk)

            transaction.on_commit(_enqueue)
    return challenge


def deliver_queued_otp(channel_code: str, phone: str, code_ref: str, challenge_id: int, *, final: bool) -> None:
    """Task side: fetch the code kept under `code_ref`, deliver it, then forget it.

    Nothing is sent once the code has expired from the cache (its challenge has expired too).
    The cached code is kept while a transient failure will be retried.
    """
    key = OTP_CODE_KEY.format(ref=code_ref)
    code = cache.get(key)
    if not code:
        return
    deliver_otp(channel_code, phone, code, challenge_id, final=final)  # raises when a retry follows
    cache.delete(key)


def deliver_otp(channel_code: str, phone: str, code: str, challenge_id: int, *, final: bool) -> None:
    """Called by the background task. On a permanent failure, keeps a safe message for the code screen.

    Raises DeliveryError only when the task should retry (`final` False and the error is transient).
    """
    channel = otp.get_channel(channel_code)
    if channel is None or channel.kind != otp.SERVER:
        return
    try:
        channel.send(phone, code)
    except otp.DeliveryError as exc:
        if exc.retryable and not final:
            raise
        cache.set(DELIVERY_FAILED_KEY.format(pk=challenge_id), exc.user_message, DELIVERY_FAILED_TTL)


def delivery_failure(phone: str, purpose: str) -> str:
    """Safe message if the latest code for this phone could not be delivered, else ""."""
    challenge = (
        OTPChallenge.objects.filter(phone=phone, purpose=purpose, consumed_at__isnull=True)
        .order_by("-created_at")
        .only("pk")
        .first()
    )
    if challenge is None:
        return ""
    return cache.get(DELIVERY_FAILED_KEY.format(pk=challenge.pk)) or ""


def _channel_available(code: str) -> bool:
    try:
        resolve_channel(code)
    except ChannelUnavailable:
        return False
    return True


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
        elif challenge is None or challenge.is_expired or not challenge.code_hmac:
            # No HMAC: a client-side (Firebase) challenge can never be answered with a typed code.
            error = InvalidCode(_("Ce code a expiré. Demande un nouveau code."))
        elif challenge.channel and not _channel_available(challenge.channel):
            # The channel was switched off in the control center after the code was sent.
            error = ChannelUnavailable(
                _("Ce moyen de recevoir le code n'est plus disponible. Demande un nouveau code.")
            )
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


def _firebase_auth_key(claims: dict) -> str:
    """One Firebase sign-in = (sub, auth_time): refreshed ID tokens of the same sign-in share it."""
    digest = hashlib.sha256(f"{claims.get('sub')}:{claims.get('auth_time')}".encode()).hexdigest()
    return FIREBASE_USED_KEY.format(digest=digest)


def verify_firebase_token(id_token: str, phone: str, purpose: str) -> str:
    """Firebase SMS channel: check the ID token and consume the pending challenge of `phone`.

    `phone` is the number our checks accepted before the browser asked Firebase to send the SMS
    (stored in the session). The token must prove that exact number. Returns the E.164 phone.
    """
    try:
        claims = verify_id_token(id_token)
    except InvalidFirebaseToken as exc:
        raise InvalidCode(str(exc)) from None
    try:
        verified = normalize_phone(claims["phone_number"], region=None)
    except InvalidPhone:
        raise InvalidCode(_("La vérification du code a échoué. Demande un nouveau code.")) from None
    if not hmac.compare_digest(verified, phone or ""):
        raise InvalidCode(_("Ce code a été validé pour un autre numéro. Recommence avec ton numéro."))
    # Same rules as every other channel, checked again at verification time.
    ensure_phone_allowed(verified)
    ensure_access_allowed(verified)
    resolve_channel(FirebaseSmsChannel.code)
    error: OTPError | None = None
    with transaction.atomic():
        challenge = (
            OTPChallenge.objects.select_for_update()
            .filter(phone=verified, purpose=purpose, consumed_at__isnull=True, channel=FirebaseSmsChannel.code)
            .order_by("-created_at")
            .first()
        )
        if challenge is None or challenge.is_expired:
            error = InvalidCode(_("Ce code a expiré. Demande un nouveau code."))
        elif not cache.add(_firebase_auth_key(claims), 1, settings.FIREBASE_MAX_AUTH_AGE_SECONDS + 60):
            # Replay: this Firebase sign-in (same sub + auth_time, whatever the token) was already used.
            error = InvalidCode(_("Ce code a déjà été utilisé. Demande un nouveau code."))
        else:
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["consumed_at"])
    if error is not None:
        raise error
    return verified


# --- Users -----------------------------------------------------------------------------------


def get_or_create_user(phone: str) -> tuple[User, bool]:
    """Return the account for a *verified* phone, creating it if needed. Never duplicates.

    Defence in depth: the platform switches and the block list are checked again here.
    """
    if not platform.feature("login"):
        raise LoginDisabled(_msg_login_disabled())
    if platform.is_phone_blocked(phone):
        raise AccountNotAllowed(_msg_blocked())
    country = next((c for c in Country.objects.all() if phone.startswith(c.phone_prefix)), None)
    user = User.objects.filter(phone=phone).first()
    created = user is None
    if created:
        if not platform.feature("signups"):
            raise SignupsClosed(_msg_signups_closed())
        try:
            with transaction.atomic():
                user = User.objects.create_user(phone=phone, country=country)
        except IntegrityError:  # concurrent sign-up with the same phone
            user = User.objects.get(phone=phone)
            created = False
    if user.is_staff or user.is_superuser or not user.is_active:  # defence in depth (audit B1, M10)
        raise AccountNotAllowed(_msg_account_not_allowed())
    user.phone_verified_at = timezone.now()
    user.last_seen_at = timezone.now()
    user.save(update_fields=["phone_verified_at", "last_seen_at"])
    return user, created


def set_full_name(user: User, full_name: str) -> None:
    if full_name and not user.full_name:
        User.objects.filter(pk=user.pk).update(full_name=full_name.strip()[:120])
        user.full_name = full_name.strip()[:120]


def set_email(user: User, email: str) -> None:
    user.email = (email or "").strip()
    user.save(update_fields=["email"])


def anonymize_user(user: User) -> None:
    """Right to erasure: called when the last profile of an account is deleted."""
    User.objects.filter(pk=user.pk).update(
        phone=f"+0{user.pk}",  # keeps the E.164 CHECK and uniqueness, frees the real number
        email="",
        full_name="",
        is_active=False,
        phone_verified_at=None,
    )
    user.set_unusable_password()
    User.objects.filter(pk=user.pk).update(password=user.password)


# --- Staff accounts (admin) ---------------------------------------------------------------------


def create_staff_user(phone: str, password: str, *, full_name: str = "", superuser: bool = False) -> User:
    """Create a staff (or superuser) account, password-protected; 2FA is enrolled at first login.

    Raises InvalidPhone, ValueError (account exists) or django ValidationError (password policy).
    """
    from django.contrib.auth.password_validation import validate_password

    phone = normalize_phone(phone)
    if User.objects.filter(phone=phone).exists():
        raise ValueError(_("Un compte existe déjà avec ce numéro."))
    validate_password(password, user=User(phone=phone, full_name=full_name))
    if superuser:
        user = User.objects.create_superuser(phone, password, full_name=full_name)
    else:
        user = User.objects.create_user(phone, password, full_name=full_name, is_staff=True)
    platform.audit(None, "user.create_staff", phone, superuser=superuser, via="create_staff")
    return user
