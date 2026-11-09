import pytest

from apps.accounts.sms import MemorySmsBackend


@pytest.fixture(autouse=True)
def _clean_state(settings):
    """Fresh SMS outbox and cache for each test."""
    from django.core.cache import cache

    MemorySmsBackend.outbox.clear()
    cache.clear()
    yield


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
