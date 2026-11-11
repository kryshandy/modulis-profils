"""Test helpers for OTP channels: platform switches, provider settings, fake Firebase tokens."""

from __future__ import annotations

import datetime as dt
import time

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

PROJECT = "modulis-test"
KID = "test-kid-1"


def set_switches(**values):
    """Update the platform singleton (e.g. otp_whatsapp_enabled=False) and drop its cache."""
    from apps.platform.services import get_settings, invalidate

    invalidate()
    site = get_settings()
    for name, value in values.items():
        setattr(site, name, value)
    site.save()
    invalidate()
    return site


def configure_whatsapp(settings):
    settings.WHATSAPP_ACCESS_TOKEN = "secret-token-xyz"
    settings.WHATSAPP_PHONE_NUMBER_ID = "1234567890"
    settings.WHATSAPP_API_VERSION = "v23.0"
    settings.WHATSAPP_OTP_TEMPLATE = "modulis_otp"
    settings.WHATSAPP_OTP_LANGUAGE = "fr"


def configure_firebase(settings):
    settings.FIREBASE_PROJECT_ID = PROJECT
    settings.FIREBASE_WEB_API_KEY = "public-api-key"
    settings.FIREBASE_WEB_AUTH_DOMAIN = f"{PROJECT}.firebaseapp.com"
    settings.FIREBASE_WEB_APP_ID = "1:123:web:abc"


class FakeResponse:
    def __init__(self, status_code: int, data):
        self.status_code = status_code
        self._data = data
        self.headers = {}

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class FirebaseKeys:
    """A local RSA key + self-signed certificate standing in for Google's securetoken keys."""

    def __init__(self):
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "securetoken.test")])
        now = dt.datetime.now(dt.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self.private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .sign(self.private_key, hashes.SHA256())
        )
        self.cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()

    def install(self, monkeypatch):
        from apps.accounts.otp import firebase

        monkeypatch.setattr(firebase, "_download_certs", lambda: ({KID: self.cert_pem}, 3600))

    def token(self, phone: str = "+237690000077", *, kid: str = KID, alg: str = "RS256", key=None, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": f"https://securetoken.google.com/{PROJECT}",
            "aud": PROJECT,
            "auth_time": now - 5,
            "user_id": "uid-123",
            "sub": "uid-123",
            "iat": now - 5,
            "exp": now + 3600,
            "phone_number": phone,
            "firebase": {"identities": {"phone": [phone]}, "sign_in_provider": "phone"},
        }
        for name, value in overrides.items():
            if value is None:
                claims.pop(name, None)
            else:
                claims[name] = value
        if alg == "HS256":
            return jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": kid})
        return jwt.encode(claims, key or self.private_key, algorithm=alg, headers={"kid": kid})
