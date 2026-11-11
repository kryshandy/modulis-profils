"""Regression tests of the security review of 3be2527..e346dcc (OTP / Firebase side)."""

import time
from unittest import mock

import pytest
from django.core.cache import cache

from apps.accounts import services, tasks
from apps.accounts.models import OTPChallenge
from apps.accounts.otp import firebase

from .otp_helpers import FirebaseKeys, configure_firebase, configure_whatsapp, set_switches

pytestmark = pytest.mark.django_db

PHONE = "+237690000077"


@pytest.fixture
def keys(settings, monkeypatch):
    configure_firebase(settings)
    k = FirebaseKeys()
    k.install(monkeypatch)
    return k


# --- 6. forced certificate refresh at most once per minute ----------------------------------


def test_unknown_kid_refreshes_certs_at_most_once_per_minute(keys, monkeypatch):
    calls = []

    def download():
        calls.append(1)
        return {"test-kid-1": keys.cert_pem}, 3600

    monkeypatch.setattr(firebase, "_download_certs", download)
    for _ in range(5):
        with pytest.raises(firebase.InvalidFirebaseToken):
            firebase.verify_id_token(keys.token(PHONE, kid=f"random-{_}"))
    assert len(calls) == 2  # initial fill + ONE forced refresh, not one per random kid
    cache.delete(firebase.CERTS_REFRESH_LOCK)  # a minute later: refresh allowed again
    with pytest.raises(firebase.InvalidFirebaseToken):
        firebase.verify_id_token(keys.token(PHONE, kid="random-x"))
    assert len(calls) == 3


# --- 7. Firebase ID token replay ------------------------------------------------------------


class TestFirebaseReplay:
    def test_same_token_cannot_consume_a_second_challenge(self, keys):
        token = keys.token(PHONE)
        services.request_otp(PHONE, "login", channel="firebase_sms")
        assert services.verify_firebase_token(token, PHONE, "login") == PHONE
        services.request_otp(PHONE, "login", channel="firebase_sms")
        with pytest.raises(services.InvalidCode, match="déjà été utilisé"):
            services.verify_firebase_token(token, PHONE, "login")
        assert OTPChallenge.objects.filter(phone=PHONE, consumed_at__isnull=True).exists()

    def test_refreshed_token_of_the_same_sign_in_is_refused(self, keys):
        auth_time = int(time.time()) - 5
        token = keys.token(PHONE, auth_time=auth_time)
        services.request_otp(PHONE, "login", channel="firebase_sms")
        services.verify_firebase_token(token, PHONE, "login")
        services.request_otp(PHONE, "login", channel="firebase_sms")
        refreshed = keys.token(PHONE, auth_time=auth_time, iat=auth_time + 2)  # same sign-in, new token
        assert refreshed != token
        with pytest.raises(services.InvalidCode):
            services.verify_firebase_token(refreshed, PHONE, "login")

    def test_a_failed_verification_does_not_burn_the_token(self, keys):
        token = keys.token(PHONE)
        with pytest.raises(services.InvalidCode):  # no pending challenge yet
            services.verify_firebase_token(token, PHONE, "login")
        services.request_otp(PHONE, "login", channel="firebase_sms")
        assert services.verify_firebase_token(token, PHONE, "login") == PHONE


# --- 8. the clear code never goes through the task queue ------------------------------------


class TestCodeNotInQueue:
    def test_task_receives_a_reference_not_the_code(self, settings, sms_outbox, django_capture_on_commit_callbacks):
        with (
            mock.patch.object(tasks, "send_otp_task") as task,
            django_capture_on_commit_callbacks(execute=True),
        ):
            services.request_otp(PHONE, "login")
        _channel, phone, ref, _pk = task.call_args.args
        assert phone == PHONE
        code = cache.get(services.OTP_CODE_KEY.format(ref=ref))
        assert code and len(code) == settings.OTP_LENGTH
        assert code not in task.call_args.args and ref != code

    def test_code_is_deleted_after_delivery(self, sms_outbox, django_capture_on_commit_callbacks):
        refs = []
        real = tasks.send_otp_task

        def spy(channel_code, phone, ref, pk):
            refs.append(ref)
            return real(channel_code, phone, ref, pk)

        with mock.patch.object(tasks, "send_otp_task", spy), django_capture_on_commit_callbacks(execute=True):
            services.request_otp(PHONE, "login")
        assert len(sms_outbox) == 1
        assert cache.get(services.OTP_CODE_KEY.format(ref=refs[0])) is None

    def test_expired_reference_sends_nothing(self, sms_outbox):
        challenge = OTPChallenge.objects.create(
            phone=PHONE, purpose="login", code_hmac="x", expires_at="2099-01-01T00:00:00Z", channel="console"
        )
        services.deliver_queued_otp("console", PHONE, "missing-ref", challenge.pk, final=True)
        assert sms_outbox == []

    def test_code_kept_while_a_retry_follows(self, settings, monkeypatch):
        from apps.accounts import otp

        configure_whatsapp(settings)
        cache.set(services.OTP_CODE_KEY.format(ref="r1"), "123456", 300)
        err = otp.DeliveryError("boom", retryable=True)
        monkeypatch.setattr(otp.CHANNELS["whatsapp"], "send", mock.Mock(side_effect=err))
        with pytest.raises(otp.DeliveryError):
            services.deliver_queued_otp("whatsapp", PHONE, "r1", 1, final=False)
        assert cache.get(services.OTP_CODE_KEY.format(ref="r1")) == "123456"
        services.deliver_queued_otp("whatsapp", PHONE, "r1", 1, final=True)  # final failure: forget the code
        assert cache.get(services.OTP_CODE_KEY.format(ref="r1")) is None


# --- 12. a code whose channel was switched off is refused -----------------------------------


def test_code_refused_when_its_channel_was_switched_off(settings, django_capture_on_commit_callbacks):
    configure_whatsapp(settings)
    with (
        mock.patch("apps.accounts.otp.whatsapp.WhatsAppChannel.send") as send,
        django_capture_on_commit_callbacks(execute=True),
    ):
        services.request_otp(PHONE, "login", channel="whatsapp")
    code = send.call_args.args[1]
    set_switches(otp_whatsapp_enabled=False)
    with pytest.raises(services.ChannelUnavailable):
        services.verify_otp(PHONE, "login", code)
    challenge = OTPChallenge.objects.get(phone=PHONE)
    assert challenge.consumed_at is None and challenge.attempts == 0
    set_switches(otp_whatsapp_enabled=True)
    services.verify_otp(PHONE, "login", code)
