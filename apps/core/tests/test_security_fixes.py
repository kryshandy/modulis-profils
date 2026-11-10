"""Regression tests for the 2026-11-10 security and code reviews (docs/revues/2026-11-10-revue-mvp.md)."""

import pytest
from django.test import RequestFactory

from apps.accounts import services as accounts
from apps.accounts.models import User
from apps.core.utils import client_ip, rate_key_ip, security_ip_hash
from apps.profiles import services as profiles
from apps.profiles.models import Profile, SlugRegistry
from tests.factories import COMPLETE_BIO, ProfileFactory, make_complete_profile

pytestmark = pytest.mark.django_db
rf = RequestFactory()


class TestStaffNeverBySms:
    """Audit B1: an SMS code must never open /gestion/."""

    def test_staff_cannot_request_otp(self, admin_user, sms_outbox):
        with pytest.raises(accounts.AccountNotAllowed):
            accounts.request_otp(admin_user.phone, "login")
        assert sms_outbox == []

    def test_inactive_cannot_request_otp(self):
        User.objects.create_user("+237690000555", is_active=False)
        with pytest.raises(accounts.AccountNotAllowed):
            accounts.request_otp("+237690000555", "login")

    def test_get_or_create_user_refuses_staff(self, admin_user):
        with pytest.raises(accounts.AccountNotAllowed):
            accounts.get_or_create_user(admin_user.phone)

    def test_login_view_shows_error_without_sms(self, client, admin_user, sms_outbox):
        response = client.post("/espace/connexion", {"phone": admin_user.phone})
        assert response.status_code == 200
        assert sms_outbox == []
        assert not client.session.get("_auth_user_id")


class TestClientIp:
    def test_forwarded_header_ignored_from_untrusted_peer(self, settings):
        settings.TRUSTED_PROXY_IPS = []
        request = rf.get("/", REMOTE_ADDR="10.0.0.1", HTTP_CF_CONNECTING_IP="1.2.3.4")
        assert client_ip(request) == "10.0.0.1"

    def test_forwarded_header_honoured_from_trusted_proxy(self, settings):
        settings.TRUSTED_PROXY_IPS = ["127.0.0.1"]
        request = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="1.2.3.4")
        assert client_ip(request) == "1.2.3.4"

    def test_ipv6_grouped_by_64(self):
        assert rate_key_ip("2001:db8:1:2::1") == rate_key_ip("2001:db8:1:2:ffff::9")
        assert rate_key_ip("2001:db8:1:2::1") != rate_key_ip("2001:db8:1:3::1")
        assert rate_key_ip("41.202.1.1") == "41.202.1.1"

    def test_security_hash_is_stable(self):
        request = rf.get("/", REMOTE_ADDR="41.202.1.1")
        assert security_ip_hash(request) == security_ip_hash(request)


class TestNearDuplicateBio:
    def test_two_words_changed_is_still_a_duplicate(self, complete_profile):
        bio = COMPLETE_BIO.replace("douze", "quinze").replace("propre", "soigné")
        copy = make_complete_profile(bio=bio)
        assert profiles.hamming(copy.bio_fingerprint, complete_profile.bio_fingerprint) <= 10
        assert not copy.is_indexable

    def test_the_original_keeps_its_indexing(self, complete_profile):
        make_complete_profile(bio=COMPLETE_BIO)
        profiles.refresh_seo_state(complete_profile)
        assert complete_profile.is_indexable


class TestErasure:
    def test_all_personal_fields_wiped_and_account_anonymised(self, django_capture_on_commit_callbacks):
        profile = ProfileFactory(custom_title="Maître plombier", district="Akwa", service_area="Littoral")
        phone = profile.user.phone
        with django_capture_on_commit_callbacks(execute=True):
            profiles.delete_profile(profile)
        profile.refresh_from_db()
        assert (profile.custom_title, profile.district, profile.service_area) == ("", "", "")
        assert not profile.photo
        user = User.objects.get(pk=profile.user_id)
        assert user.phone != phone and not user.is_active and user.full_name == ""
        assert not User.objects.filter(phone=phone).exists()  # the number can sign up again

    def test_account_kept_while_another_page_exists(self):
        profile = ProfileFactory()
        profiles.create_profile(profile.user, "Deuxième activité")
        profiles.delete_profile(profile)
        profile.user.refresh_from_db()
        assert profile.user.is_active

    def test_erased_slug_hash_is_keyed(self, settings):
        settings.SLUG_HASH_KEY = "a" * 40
        first = profiles.slug_hash("jean-dupont")
        settings.SLUG_HASH_KEY = "b" * 40
        assert profiles.slug_hash("jean-dupont") != first


def test_get_or_create_profile_is_idempotent():
    _u, first, created = profiles.get_or_create_profile("+237690000777", "Paul Nkoulou")
    _u, second, created2 = profiles.get_or_create_profile("+237690000777", "Paul Nkoulou")
    assert created and not created2 and first.pk == second.pk
    assert Profile.objects.filter(user__phone="+237690000777").count() == 1
    assert SlugRegistry.objects.filter(profile=first, kind="current").count() == 1
