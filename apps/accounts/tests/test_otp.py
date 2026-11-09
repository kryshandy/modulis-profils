import re
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import OTPChallenge

pytestmark = pytest.mark.django_db

PHONE = "+237690000001"


def _code_from(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)


class TestNormalizePhone:
    @pytest.mark.parametrize("raw", ["690000001", "6 90 00 00 01", "+237 690 000 001", "00237690000001"])
    def test_cameroon_formats(self, raw):
        assert services.normalize_phone(raw) == PHONE

    @pytest.mark.parametrize("raw", ["", "123", "abc", "+2371"])
    def test_invalid(self, raw):
        with pytest.raises(services.InvalidPhone):
            services.normalize_phone(raw)


class TestRequestOtp:
    def test_sends_sms_and_stores_only_hmac(self, sms_outbox, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            challenge = services.request_otp(PHONE, "login", ip_hash="ip1")
        assert len(sms_outbox) == 1
        code = _code_from(sms_outbox)
        assert code not in challenge.code_hmac
        assert len(challenge.code_hmac) == 64

    def test_foreign_prefix_refused(self):
        with pytest.raises(services.PhoneNotAllowed):
            services.request_otp("+33612345678", "login")

    def test_per_phone_limit(self, settings):
        settings.OTP_MAX_SENDS_PER_PHONE_PER_HOUR = 2
        services.request_otp(PHONE, "login", ip_hash="a")
        services.request_otp(PHONE, "login", ip_hash="b")
        with pytest.raises(services.TooManyRequests):
            services.request_otp(PHONE, "login", ip_hash="c")

    def test_per_ip_limit(self, settings):
        settings.OTP_MAX_SENDS_PER_IP_PER_HOUR = 2
        services.request_otp("+237690000002", "login", ip_hash="same")
        services.request_otp("+237690000003", "login", ip_hash="same")
        with pytest.raises(services.TooManyRequests):
            services.request_otp("+237690000004", "login", ip_hash="same")

    def test_global_daily_cap(self, settings):
        settings.OTP_MAX_SENDS_PER_DAY_GLOBAL = 1
        services.request_otp("+237690000002", "login")
        with pytest.raises(services.TooManyRequests):
            services.request_otp("+237690000003", "login")

    def test_new_code_invalidates_previous(self, sms_outbox, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            services.request_otp(PHONE, "login")
        first = _code_from(sms_outbox)
        with django_capture_on_commit_callbacks(execute=True):
            services.request_otp(PHONE, "login")
        second = _code_from(sms_outbox)
        if first != second:
            with pytest.raises(services.InvalidCode):
                services.verify_otp(PHONE, "login", first)
        services.verify_otp(PHONE, "login", second)


class TestVerifyOtp:
    def _send(self, outbox, capture):
        with capture(execute=True):
            services.request_otp(PHONE, "login")
        return _code_from(outbox)

    def test_success_is_single_use(self, sms_outbox, django_capture_on_commit_callbacks):
        code = self._send(sms_outbox, django_capture_on_commit_callbacks)
        services.verify_otp(PHONE, "login", code)
        with pytest.raises(services.InvalidCode):
            services.verify_otp(PHONE, "login", code)

    def test_wrong_purpose(self, sms_outbox, django_capture_on_commit_callbacks):
        code = self._send(sms_outbox, django_capture_on_commit_callbacks)
        with pytest.raises(services.InvalidCode):
            services.verify_otp(PHONE, "card", code)

    def test_expired(self, sms_outbox, django_capture_on_commit_callbacks):
        code = self._send(sms_outbox, django_capture_on_commit_callbacks)
        OTPChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        with pytest.raises(services.InvalidCode):
            services.verify_otp(PHONE, "login", code)

    def test_attempts_are_capped(self, sms_outbox, django_capture_on_commit_callbacks, settings):
        code = self._send(sms_outbox, django_capture_on_commit_callbacks)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(settings.OTP_MAX_ATTEMPTS):
            with pytest.raises(services.InvalidCode):
                services.verify_otp(PHONE, "login", wrong)
        with pytest.raises(services.TooManyRequests):
            services.verify_otp(PHONE, "login", code)  # even the right code is now refused


class TestGetOrCreateUser:
    def test_never_duplicates(self):
        user1, created1 = services.get_or_create_user(PHONE)
        user2, created2 = services.get_or_create_user(PHONE)
        assert created1 and not created2
        assert user1.pk == user2.pk
        assert user1.has_usable_password() is False
        assert user2.phone_verified_at is not None
