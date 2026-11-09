import pytest
from django.urls import reverse

from apps.accounts.models import OTPChallenge, User
from tests.factories import ProfileFactory

from .helpers import code_from

pytestmark = pytest.mark.django_db

PHONE_RAW = "690 00 00 11"
PHONE = "+237690000011"


def _request_code(client, capture, phone=PHONE_RAW):
    with capture(execute=True):
        return client.post(reverse("dashboard:login"), {"phone": phone})


def test_login_page_renders(client):
    response = client.get(reverse("dashboard:login"))
    assert response.status_code == 200
    body = response.content.decode()
    assert 'autocomplete="tel"' in body
    assert 'inputmode="numeric"' in body
    assert "+237" in body


def test_full_login_flow_new_user_goes_to_onboarding(client, sms_outbox, django_capture_on_commit_callbacks):
    response = _request_code(client, django_capture_on_commit_callbacks)
    assert response.status_code == 302
    assert response["Location"] == reverse("dashboard:verify")
    assert PHONE not in response["Location"]  # never in the URL
    assert client.session["otp_phone"] == PHONE
    verify_page = client.get(reverse("dashboard:verify"))
    assert 'autocomplete="one-time-code"' in verify_page.content.decode()

    response = client.post(reverse("dashboard:verify"), {"action": "verify", "code": code_from(sms_outbox)})
    assert response.status_code == 302
    assert response["Location"] == reverse("dashboard:onboarding", kwargs={"step": "nom"})
    assert User.objects.filter(phone=PHONE).exists()
    assert "otp_phone" not in client.session
    assert client.session["_auth_user_id"] == str(User.objects.get(phone=PHONE).pk)


def test_existing_user_with_profile_goes_home(client, sms_outbox, django_capture_on_commit_callbacks):
    ProfileFactory(user__phone=PHONE)
    _request_code(client, django_capture_on_commit_callbacks)
    response = client.post(reverse("dashboard:verify"), {"action": "verify", "code": code_from(sms_outbox)})
    assert response["Location"] == reverse("dashboard:home")


def test_login_rotates_session_key(client, sms_outbox, django_capture_on_commit_callbacks):
    _request_code(client, django_capture_on_commit_callbacks)
    before = client.session.session_key
    client.post(reverse("dashboard:verify"), {"action": "verify", "code": code_from(sms_outbox)})
    assert client.session.session_key != before


def test_invalid_phone_message(client):
    response = client.post(reverse("dashboard:login"), {"phone": "123"})
    assert response.status_code == 200
    assert "pas valide" in response.content.decode()


def test_wrong_code_message_and_attempt_is_counted(client, sms_outbox, django_capture_on_commit_callbacks):
    _request_code(client, django_capture_on_commit_callbacks)
    good = code_from(sms_outbox)
    wrong = "000000" if good != "000000" else "111111"
    response = client.post(reverse("dashboard:verify"), {"action": "verify", "code": wrong})
    assert response.status_code == 200
    assert "Code incorrect" in response.content.decode()
    assert OTPChallenge.objects.get(phone=PHONE, consumed_at__isnull=True).attempts == 1


def test_code_format_error(client, sms_outbox, django_capture_on_commit_callbacks):
    _request_code(client, django_capture_on_commit_callbacks)
    response = client.post(reverse("dashboard:verify"), {"action": "verify", "code": "12"})
    assert "6 chiffres" in response.content.decode()


def test_otp_send_limit_message(client, settings, django_capture_on_commit_callbacks):
    settings.OTP_MAX_SENDS_PER_PHONE_PER_HOUR = 1
    _request_code(client, django_capture_on_commit_callbacks)
    response = client.post(reverse("dashboard:login"), {"phone": PHONE_RAW})
    assert response.status_code == 200
    assert "Trop de codes" in response.content.decode()


def test_too_many_wrong_codes_message(client, settings, sms_outbox, django_capture_on_commit_callbacks):
    settings.OTP_MAX_ATTEMPTS = 2
    _request_code(client, django_capture_on_commit_callbacks)
    good = code_from(sms_outbox)
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(2):
        client.post(reverse("dashboard:verify"), {"action": "verify", "code": wrong})
    response = client.post(reverse("dashboard:verify"), {"action": "verify", "code": good})
    assert "Trop d&#x27;essais" in response.content.decode()


def test_resend_is_throttled_for_60_seconds(client, django_capture_on_commit_callbacks):
    _request_code(client, django_capture_on_commit_callbacks)
    response = client.post(reverse("dashboard:verify"), {"action": "resend"})
    assert response.status_code == 200
    assert "Patiente encore" in response.content.decode()
    assert OTPChallenge.objects.filter(phone=PHONE).count() == 1


def test_resend_after_delay(client, django_capture_on_commit_callbacks):
    _request_code(client, django_capture_on_commit_callbacks)
    session = client.session
    session["otp_sent_at"] = 0
    session.save()
    response = client.post(reverse("dashboard:verify"), {"action": "resend"})
    assert response.status_code == 302
    assert OTPChallenge.objects.filter(phone=PHONE).count() == 2


def test_verify_without_pending_phone_redirects(client):
    response = client.get(reverse("dashboard:verify"))
    assert response["Location"] == reverse("dashboard:login")


def test_logout_is_post_only(logged_client):
    assert logged_client.get(reverse("dashboard:logout")).status_code == 405
    response = logged_client.post(reverse("dashboard:logout"))
    assert response.status_code == 302
    assert "_auth_user_id" not in logged_client.session


@pytest.mark.parametrize(
    "name,kwargs",
    [
        ("home", {}),
        ("edit", {"section": "identite"}),
        ("share", {}),
        ("cards", {}),
        ("stats", {}),
        ("settings", {}),
        ("help", {}),
        ("onboarding", {"step": "nom"}),
        ("slug_check", {}),
    ],
)
def test_login_required(client, name, kwargs):
    url = reverse(f"dashboard:{name}", kwargs=kwargs)
    response = client.get(url)
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("dashboard:login"))


def test_logged_user_on_login_page_goes_home(logged_client):
    assert logged_client.get(reverse("dashboard:login"))["Location"] == reverse("dashboard:home")
