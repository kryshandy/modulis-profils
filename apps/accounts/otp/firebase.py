"""OTP by SMS through Firebase Authentication (phone provider), verified without firebase-admin.

The browser (static/js/firebase-otp.js) asks Firebase to send and check the SMS code, then posts the
Firebase ID token to our server. We verify it as documented in
https://firebase.google.com/docs/auth/admin/verify-id-tokens ("third-party JWT library"):
- header: alg == RS256, kid one of Google's securetoken certificates (cached per Cache-Control max-age);
- payload: exp in the future, iat and auth_time in the past, aud == project id,
  iss == https://securetoken.google.com/<project id>, sub non-empty;
- plus our own rules: firebase.sign_in_provider == "phone", a phone_number claim, a recent auth_time.
"""

from __future__ import annotations

import re
import time

import jwt
import requests
from cryptography import x509
from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from .base import CLIENT, OTPChannel

CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
CERTS_CACHE_KEY = "firebase:securetoken:certs:v1"
CERTS_REFRESH_LOCK = "firebase:securetoken:certs:refresh-lock"
CERTS_REFRESH_COOLDOWN = 60  # seconds
DEFAULT_CERTS_MAX_AGE = 3600
CLOCK_SKEW = 10  # seconds tolerated on exp / iat / auth_time
MAX_AGE_RE = re.compile(r"max-age=(\d+)")


class InvalidFirebaseToken(Exception):
    """`str(error)` is safe to show; details stay in `reason`."""

    def __init__(self, reason: str, message=None):
        self.reason = reason
        super().__init__(str(message or _("La vérification du code a échoué. Demande un nouveau code.")))


class FirebaseSmsChannel(OTPChannel):
    code = "firebase_sms"
    kind = CLIENT
    label = _("SMS via Firebase Authentication")
    choice_label = _("Recevoir le code par SMS")
    choice_help = _("Un SMS classique sur ton téléphone.")
    code_label = _("Code reçu par SMS")
    verify_hint = _("Tu vas recevoir un SMS avec ton code à 6 chiffres. Il peut mettre jusqu'à une minute à arriver.")

    def is_configured(self) -> bool:
        return bool(
            settings.FIREBASE_PROJECT_ID
            and settings.FIREBASE_WEB_API_KEY
            and settings.FIREBASE_WEB_AUTH_DOMAIN
            and settings.FIREBASE_WEB_APP_ID
        )

    @staticmethod
    def web_config() -> dict:
        """Public web configuration (not secret: it identifies the Firebase project)."""
        return {
            "apiKey": settings.FIREBASE_WEB_API_KEY,
            "authDomain": settings.FIREBASE_WEB_AUTH_DOMAIN,
            "projectId": settings.FIREBASE_PROJECT_ID,
            "appId": settings.FIREBASE_WEB_APP_ID,
        }


# --- Google public certificates --------------------------------------------------------------


def _download_certs() -> tuple[dict[str, str], int]:
    """Fetch {kid: PEM certificate} and its cache lifetime (Cache-Control max-age)."""
    response = requests.get(CERTS_URL, timeout=5)
    response.raise_for_status()
    match = MAX_AGE_RE.search(response.headers.get("Cache-Control", ""))
    max_age = int(match.group(1)) if match else DEFAULT_CERTS_MAX_AGE
    certs = response.json()
    if not isinstance(certs, dict):
        raise ValueError("unexpected certificate document")
    return certs, max_age


def get_certs(*, force: bool = False) -> dict[str, str]:
    certs = None if force else cache.get(CERTS_CACHE_KEY)
    if certs is None:
        try:
            certs, max_age = _download_certs()
        except (requests.RequestException, ValueError) as exc:
            raise InvalidFirebaseToken(
                f"certs unavailable ({type(exc).__name__})",
                _("La vérification est momentanément indisponible. Réessaie dans un instant."),
            ) from None
        cache.set(CERTS_CACHE_KEY, certs, max(60, min(max_age, 24 * 3600)))
    return certs


def _public_key(kid: str):
    certs = get_certs()
    pem = certs.get(kid)
    # Key rotation: refresh, but at most once per CERTS_REFRESH_COOLDOWN (random kids must not let
    # anyone make us hammer Google's endpoint).
    if pem is None and cache.add(CERTS_REFRESH_LOCK, 1, CERTS_REFRESH_COOLDOWN):
        pem = get_certs(force=True).get(kid)
    if pem is None:
        raise InvalidFirebaseToken("unknown kid")
    return x509.load_pem_x509_certificate(pem.encode()).public_key()


# --- ID token --------------------------------------------------------------------------------


def verify_id_token(id_token: str) -> dict:
    """Return the verified claims of a Firebase ID token obtained by phone sign-in, or raise."""
    project = settings.FIREBASE_PROJECT_ID
    if not project:
        raise InvalidFirebaseToken("firebase not configured")
    if not id_token or not isinstance(id_token, str) or len(id_token) > 4096:
        raise InvalidFirebaseToken("malformed token")
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError:
        raise InvalidFirebaseToken("malformed header") from None
    if header.get("alg") != "RS256":
        raise InvalidFirebaseToken("bad alg")
    kid = header.get("kid")
    if not kid or not isinstance(kid, str):
        raise InvalidFirebaseToken("missing kid")
    key = _public_key(kid)
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=project,
            issuer=f"https://securetoken.google.com/{project}",
            leeway=CLOCK_SKEW,
            options={"require": ["exp", "iat", "aud", "iss", "sub", "auth_time"]},
        )
    except jwt.ExpiredSignatureError:
        raise InvalidFirebaseToken("expired", _("Ce code a expiré. Demande un nouveau code.")) from None
    except jwt.PyJWTError as exc:
        raise InvalidFirebaseToken(f"invalid ({type(exc).__name__})") from None

    now = time.time()
    iat, auth_time = claims.get("iat"), claims.get("auth_time")
    if not isinstance(iat, int | float) or iat > now + CLOCK_SKEW:
        raise InvalidFirebaseToken("iat in the future")
    if not isinstance(auth_time, int | float) or auth_time > now + CLOCK_SKEW:
        raise InvalidFirebaseToken("auth_time in the future")
    if now - auth_time > settings.FIREBASE_MAX_AUTH_AGE_SECONDS:
        # The phone must have been verified just now, not an hour ago with a replayed token.
        raise InvalidFirebaseToken("stale auth_time", _("Ce code a expiré. Demande un nouveau code."))
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip() or len(sub) > 128:
        raise InvalidFirebaseToken("bad sub")
    firebase_claim = claims.get("firebase")
    provider = firebase_claim.get("sign_in_provider") if isinstance(firebase_claim, dict) else None
    if provider != "phone":
        raise InvalidFirebaseToken("not a phone sign-in")
    phone = claims.get("phone_number")
    if not isinstance(phone, str) or not phone.startswith("+"):
        raise InvalidFirebaseToken("missing phone_number")
    return claims
