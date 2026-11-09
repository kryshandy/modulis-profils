"""IDOR: user B must never see nor change anything belonging to user A."""

import pytest
from django.urls import reverse

from apps.cards.models import Card
from apps.profiles.models import ProfileLink, ProfileMedia, ProfileService
from tests.factories import CardFactory, ProfileFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def victim(db):
    profile = ProfileFactory(display_name="Profil Victime")
    service = ProfileService.objects.create(profile=profile, title="Service A")
    media = ProfileMedia.objects.create(profile=profile, image="a.webp", caption="Photo A")
    link = ProfileLink.objects.create(profile=profile, kind="website", url="https://a.test")
    card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
    return {"profile": profile, "service": service, "media": media, "link": link, "card": card}


@pytest.fixture
def attacker(client):
    profile = ProfileFactory(display_name="Profil Attaquant")
    client.force_login(profile.user)
    return client


@pytest.mark.parametrize(
    "name,key,data",
    [
        ("service_update", "service", {"title": "pwned"}),
        ("service_delete", "service", {}),
        ("service_move", "service", {"direction": "down"}),
        ("media_update", "media", {"caption": "pwned"}),
        ("media_delete", "media", {}),
        ("media_move", "media", {"direction": "down"}),
        ("link_delete", "link", {}),
        ("link_move", "link", {"direction": "down"}),
        ("card_lost", "card", {}),
    ],
)
def test_cannot_touch_other_users_objects(attacker, victim, name, key, data):
    obj = victim[key]
    response = attacker.post(reverse(f"dashboard:{name}", args=[obj.pk]), data)
    assert response.status_code == 404
    obj.refresh_from_db()
    if key == "service":
        assert obj.title == "Service A"
    if key == "media":
        assert obj.caption == "Photo A"
    if key == "card":
        assert obj.status == Card.Status.ACTIVE
    assert type(obj).objects.filter(pk=obj.pk).exists()


def test_cannot_switch_to_other_users_profile(attacker, victim):
    response = attacker.post(reverse("dashboard:switch_profile"), {"profile_id": victim["profile"].pk})
    assert response.status_code == 400
    home = attacker.get(reverse("dashboard:home")).content.decode()
    assert "Profil Victime" not in home
    assert "Profil Attaquant" in home


def test_session_tampering_ignored(attacker, victim):
    session = attacker.session
    session["dashboard_profile_id"] = victim["profile"].pk
    session.save()
    response = attacker.post(
        reverse("dashboard:edit", kwargs={"section": "identite"}), {"display_name": "pwned", "kind": "person"}
    )
    assert response.status_code == 302
    victim["profile"].refresh_from_db()
    assert victim["profile"].display_name == "Profil Victime"


def test_other_users_cards_not_listed(attacker, victim):
    body = attacker.get(reverse("dashboard:cards")).content.decode()
    assert victim["card"].public_code not in body


def test_htmx_post_without_csrf_rejected(victim):
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    client.force_login(victim["profile"].user)
    response = client.post(reverse("dashboard:tour_done"), HTTP_HX_REQUEST="true")
    assert response.status_code == 403
