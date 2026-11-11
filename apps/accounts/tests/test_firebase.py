"""Firebase ID-token verification without firebase-admin (ADR-0009), with a local key + self-signed cert."""

import time

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.accounts import services
from apps.accounts.models import OTPChallenge
from apps.accounts.otp import firebase
from tests.factories import UserFactory

from .otp_helpers import PROJECT, FirebaseKeys, configure_firebase, set_switches

pytestmark = pytest.mark.django_db

PHONE = "+237690000077"


@pytest.fixture
def keys(settings, monkeypatch):
    configure_firebase(settings)
    k = FirebaseKeys()
    k.install(monkeypatch)
    return k


class TestVerifyIdToken:
    def test_valid_token(self, keys):
        claims = firebase.verify_id_token(keys.token(PHONE))
        assert claims["phone_number"] == PHONE and claims["sub"] == "uid-123"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"aud": "other-project"},
            {"iss": "https://securetoken.google.com/other-project"},
            {"iss": f"https://accounts.google.com/{PROJECT}"},
            {"exp": int(time.time()) - 60},
            {"iat": int(time.time()) + 3600},
            {"auth_time": int(time.time()) + 3600},
            {"auth_time": int(time.time()) - 3600},  # verified an hour ago: replay
            {"sub": ""},
            {"sub": None},
            {"auth_time": None},
            {"firebase": {"sign_in_provider": "password"}},
            {"firebase": {"sign_in_provider": "google.com"}},
            {"firebase": None},
            {"phone_number": None},
            {"phone_number": "690000077"},
        ],
    )
    def test_invalid_claims(self, keys, overrides):
        with pytest.raises(firebase.InvalidFirebaseToken):
            firebase.verify_id_token(keys.token(PHONE, **overrides))

    def test_expired_message(self, keys):
        with pytest.raises(firebase.InvalidFirebaseToken) as exc:
            firebase.verify_id_token(keys.token(PHONE, exp=int(time.time()) - 60))
        assert "expiré" in str(exc.value)

    def test_wrong_signing_key(self, keys):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(firebase.InvalidFirebaseToken):
            firebase.verify_id_token(keys.token(PHONE, key=other))

    def test_unknown_kid_refreshes_once_then_fails(self, keys, monkeypatch):
        calls = []

        def download():
            calls.append(1)
            return {"test-kid-1": keys.cert_pem}, 3600

        monkeypatch.setattr(firebase, "_download_certs", download)
        with pytest.raises(firebase.InvalidFirebaseToken):
            firebase.verify_id_token(keys.token(PHONE, kid="unknown"))
        assert len(calls) == 2  # cache miss + forced refresh

    def test_certs_are_cached(self, keys, monkeypatch):
        calls = []

        def download():
            calls.append(1)
            return {"test-kid-1": keys.cert_pem}, 3600

        monkeypatch.setattr(firebase, "_download_certs", download)
        firebase.verify_id_token(keys.token(PHONE))
        firebase.verify_id_token(keys.token(PHONE))
        assert len(calls) == 1

    def test_hs256_refused(self, keys):
        with pytest.raises(firebase.InvalidFirebaseToken):
            firebase.verify_id_token(keys.token(PHONE, alg="HS256"))

    @pytest.mark.parametrize("token", ["", "abc", "a.b.c", "x" * 5000])
    def test_garbage(self, keys, token):
        with pytest.raises(firebase.InvalidFirebaseToken):
            firebase.verify_id_token(token)

    def test_not_configured(self, keys, settings):
        settings.FIREBASE_PROJECT_ID = ""
        with pytest.raises(firebase.InvalidFirebaseToken):
            firebase.verify_id_token(keys.token(PHONE))

    def test_cert_download_failure_is_a_safe_error(self, keys, monkeypatch):
        import requests

        def fail():
            raise requests.ConnectionError("down")

        monkeypatch.setattr(firebase, "_download_certs", fail)
        with pytest.raises(firebase.InvalidFirebaseToken) as exc:
            firebase.verify_id_token(keys.token(PHONE))
        assert "indisponible" in str(exc.value)

    def test_max_age_parsing(self, monkeypatch):
        class Resp:
            headers = {"Cache-Control": "public, max-age=19302, must-revalidate, no-transform"}

            def raise_for_status(self):
                pass

            def json(self):
                return {"k": "pem"}

        monkeypatch.setattr(firebase.requests, "get", lambda url, timeout: Resp())
        assert firebase._download_certs() == ({"k": "pem"}, 19302)


class TestVerifyFirebaseToken:
    def _pending(self):
        return services.request_otp(PHONE, "login", channel="firebase_sms")

    def test_valid_consumes_pending_challenge(self, keys):
        challenge = self._pending()
        assert services.verify_firebase_token(keys.token(PHONE), PHONE, "login") == PHONE
        challenge.refresh_from_db()
        assert challenge.consumed_at is not None
        with pytest.raises(services.InvalidCode):  # single use
            services.verify_firebase_token(keys.token(PHONE), PHONE, "login")

    def test_without_pending_challenge(self, keys):
        with pytest.raises(services.InvalidCode):
            services.verify_firebase_token(keys.token(PHONE), PHONE, "login")

    def test_other_phone_than_the_checked_one(self, keys):
        self._pending()
        with pytest.raises(services.InvalidCode):
            services.verify_firebase_token(keys.token("+237690000078"), PHONE, "login")
        assert OTPChallenge.objects.get().consumed_at is None

    def test_wrong_purpose(self, keys):
        self._pending()
        with pytest.raises(services.InvalidCode):
            services.verify_firebase_token(keys.token(PHONE), PHONE, "card")

    def test_staff_phone_refused(self, keys):
        self._pending()
        UserFactory(phone=PHONE, is_staff=True)  # became staff after the send
        with pytest.raises(services.AccountNotAllowed):
            services.verify_firebase_token(keys.token(PHONE), PHONE, "login")

    def test_signups_off(self, keys):
        self._pending()
        set_switches(signups_enabled=False)
        with pytest.raises(services.SignupsClosed):
            services.verify_firebase_token(keys.token(PHONE), PHONE, "login")

    def test_channel_switched_off_meanwhile(self, keys):
        self._pending()
        set_switches(otp_firebase_sms_enabled=False)
        with pytest.raises(services.ChannelUnavailable):
            services.verify_firebase_token(keys.token(PHONE), PHONE, "login")

    def test_invalid_token_is_invalid_code(self, keys):
        self._pending()
        with pytest.raises(services.InvalidCode):
            services.verify_firebase_token(keys.token(PHONE, aud="evil"), PHONE, "login")
