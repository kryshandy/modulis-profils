"""CSP: third-party hosts only on the responses that need them (security review 3be2527..e346dcc)."""

import pytest
from django.urls import reverse

from apps.accounts.tests.otp_helpers import configure_firebase
from apps.cards.models import Card
from apps.core import csp
from apps.seo.tests.utils import indexable_profile
from tests.factories import CardFactory

pytestmark = pytest.mark.django_db

GOOGLE_HOSTS = ("google.com", "gstatic.com", "googleapis.com", "firebaseapp.com")


def _policy(response) -> str:
    return response["Content-Security-Policy"]


def _no_third_party(policy: str) -> None:
    for host in (*GOOGLE_HOSTS, "challenges.cloudflare.com"):
        assert host not in policy, host


def test_home_and_public_profile_have_a_self_only_policy(client):
    _no_third_party(_policy(client.get("/")))
    profile = indexable_profile()
    response = client.get(f"/{profile.slug}")
    assert response.status_code == 200
    _no_third_party(_policy(response))


def test_login_without_turnstile_key_is_self_only(client):
    _no_third_party(_policy(client.get(reverse("dashboard:login"))))


def test_login_with_turnstile_allows_cloudflare_only(client, settings):
    settings.TURNSTILE_SITE_KEY = "1x00000000000000000000AA"
    policy = _policy(client.get(reverse("dashboard:login")))
    assert "https://challenges.cloudflare.com" in policy
    assert not any(host in policy for host in GOOGLE_HOSTS)


def test_firebase_verify_page_allows_google_hosts(client, settings):
    configure_firebase(settings)
    client.post(reverse("dashboard:login"), {"phone": "690 00 00 77", "channel": "firebase_sms"})
    policy = _policy(client.get(reverse("dashboard:verify")))
    for source in ("https://www.gstatic.com", "https://identitytoolkit.googleapis.com", "https://*.firebaseapp.com"):
        assert source in policy
    assert "challenges.cloudflare.com" not in policy


def test_card_activation_otp_step_allows_firebase(client, settings, django_capture_on_commit_callbacks):
    configure_firebase(settings)
    card = CardFactory(status=Card.Status.STOCK)
    url = reverse("cards:activate", args=[card.public_code])
    from apps.cards.tests.test_channels import GOOD_CODE

    first = client.get(url)
    _no_third_party(_policy(first))  # code step without Turnstile key
    client.post(url, {"activation_code": GOOD_CODE})
    client.post(url, {"phone": "690 00 00 77", "channel": "firebase_sms"})
    policy = _policy(client.get(url))
    assert "https://www.gstatic.com" in policy and "https://identitytoolkit.googleapis.com" in policy


def test_allow_merges_policies_without_duplicates():
    response = type("R", (), {})()
    csp.allow(response, csp.TURNSTILE)
    csp.allow(response, csp.FIREBASE, csp.TURNSTILE)
    assert response._csp_update["frame-src"].count("https://challenges.cloudflare.com") == 1
    assert "https://www.google.com" in response._csp_update["frame-src"]
