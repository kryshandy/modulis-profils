import pytest
from django.test import Client

from apps.accounts.sms import MemorySmsBackend


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_2fa: do not mark force_login() staff sessions as 2FA-verified (tests of the 2FA itself).",
    )


@pytest.fixture(autouse=True)
def _clean_state(settings):
    """Fresh SMS outbox and cache for each test."""
    from django.core.cache import cache

    MemorySmsBackend.outbox.clear()
    cache.clear()
    yield


@pytest.fixture(autouse=True)
def _staff_sessions_pass_2fa(request, monkeypatch):
    """Staff 2FA is ON in tests (STAFF_2FA_REQUIRED). A staff session opened with force_login() (the
    admin_client fixture included) is marked as verified, like after a real TOTP check, so admin tests
    exercise the admin itself. Production code is unchanged; tests marked `real_2fa` opt out.
    """
    if request.node.get_closest_marker("real_2fa"):
        return
    original = Client.force_login

    def force_login(self, user, backend=None):
        original(self, user, backend)
        if user.is_staff:
            from apps.security.testing import mark_otp_verified

            mark_otp_verified(self, user)

    monkeypatch.setattr(Client, "force_login", force_login)


@pytest.fixture
def admin_user(db, django_user_model):
    """pytest-django's default uses phone="admin", which violates the E.164 CHECK constraint."""
    return django_user_model.objects.create_superuser(phone="+237699999999", password="admin-password-123")


@pytest.fixture
def sms_outbox():
    return MemorySmsBackend.outbox


@pytest.fixture
def user(db):
    from tests.factories import UserFactory

    return UserFactory()


@pytest.fixture
def profile(db):
    from tests.factories import ProfileFactory

    return ProfileFactory()


@pytest.fixture
def complete_profile(db):
    from tests.factories import make_complete_profile

    return make_complete_profile()


@pytest.fixture
def logged_client(client, profile):
    client.force_login(profile.user)
    return client
