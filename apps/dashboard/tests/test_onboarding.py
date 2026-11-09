import pytest
from django.urls import reverse
from PIL import Image

from apps.core.models import City, Trade
from apps.profiles.models import Profile
from tests.factories import UserFactory

from .helpers import make_image

pytestmark = pytest.mark.django_db


def url(step):
    return reverse("dashboard:onboarding", kwargs={"step": step})


@pytest.fixture
def new_client(client):
    user = UserFactory(phone="+237690000077", full_name="")
    client.force_login(user)
    client.user = user
    return client


def _step1(client, name="Awa Ngono", kind="person"):
    return client.post(url("nom"), {"display_name": name, "kind": kind})


def test_step1_creates_exactly_one_profile_and_is_idempotent(new_client):
    response = _step1(new_client)
    assert response["Location"] == url("metier")
    assert Profile.objects.filter(user=new_client.user).count() == 1
    _step1(new_client, name="Awa Ngono Couture", kind="business")
    profiles = Profile.objects.filter(user=new_client.user)
    assert profiles.count() == 1
    profile = profiles.get()
    assert profile.display_name == "Awa Ngono Couture"
    assert profile.kind == "business"
    assert profile.whatsapp == new_client.user.phone  # prefilled with the account phone
    assert profile.slugs.filter(kind="current").exists()


def test_steps_require_profile(new_client):
    assert new_client.get(url("contact"))["Location"] == url("nom")


def test_step2_trade_and_city(new_client):
    _step1(new_client)
    trade = Trade.objects.filter(is_active=True).first()
    city = City.objects.get(slug="douala")
    response = new_client.post(url("metier"), {"trade_choice": str(trade.pk), "city": city.pk, "district": "Akwa"})
    assert response["Location"] == url("contact")
    profile = Profile.objects.get(user=new_client.user)
    assert profile.trade == trade and profile.city == city and profile.district == "Akwa"
    assert profile.completeness_score >= 20


def test_step2_custom_title(new_client):
    _step1(new_client)
    city = City.objects.get(slug="douala")
    new_client.post(
        url("metier"), {"trade_choice": "other", "custom_title": "Réparatrice de téléphones", "city": city.pk}
    )
    profile = Profile.objects.get(user=new_client.user)
    assert profile.trade is None
    assert profile.custom_title == "Réparatrice de téléphones"


def test_step2_requires_a_trade(new_client):
    _step1(new_client)
    city = City.objects.get(slug="douala")
    response = new_client.post(url("metier"), {"trade_choice": "", "city": city.pk})
    assert response.status_code == 200
    assert "Choisis ton métier" in response.content.decode()


def test_steps_3_to_5_need_step_2_and_are_skippable(new_client):
    _step1(new_client)
    assert new_client.get(url("contact"))["Location"] == url("metier")
    trade = Trade.objects.first()
    new_client.post(url("metier"), {"trade_choice": str(trade.pk), "city": City.objects.get(slug="douala").pk})
    assert new_client.post(url("contact"), {"action": "skip"})["Location"] == url("photo")
    assert new_client.post(url("photo"), {"action": "later"})["Location"] == url("fin")


def test_step3_contact_normalises_numbers(new_client):
    _step1(new_client)
    new_client.post(url("metier"), {"trade_choice": str(Trade.objects.first().pk), "city": City.objects.first().pk})
    response = new_client.post(url("contact"), {"whatsapp": "699 11 22 33", "phone_public": "", "email_public": ""})
    assert response["Location"] == url("photo")
    assert Profile.objects.get(user=new_client.user).whatsapp == "+237699112233"


def test_step3_invalid_number(new_client):
    _step1(new_client)
    new_client.post(url("metier"), {"trade_choice": str(Trade.objects.first().pk), "city": City.objects.first().pk})
    response = new_client.post(url("contact"), {"whatsapp": "12", "phone_public": ""})
    assert response.status_code == 200
    assert "pas valide" in response.content.decode()


def test_step4_photo_reencoded_webp(new_client):
    _step1(new_client)
    new_client.post(url("metier"), {"trade_choice": str(Trade.objects.first().pk), "city": City.objects.first().pk})
    response = new_client.post(url("photo"), {"photo": make_image()})
    assert response["Location"] == url("presentation")
    profile = Profile.objects.get(user=new_client.user)
    assert profile.photo.name.endswith(".webp")
    with profile.photo.open("rb") as fh, Image.open(fh) as img:
        assert img.format == "WEBP"
        assert max(img.size) == 800


def test_step5_bio_and_two_services_then_finish(new_client):
    _step1(new_client)
    new_client.post(url("metier"), {"trade_choice": str(Trade.objects.first().pk), "city": City.objects.first().pk})
    bio = "Je répare et j'installe tout ce qui touche à l'eau dans la maison, rapidement et proprement. " * 2
    response = new_client.post(
        url("presentation"),
        {"bio": bio, "service_1": "Réparation de fuite", "price_1": "dès 5 000 FCFA", "service_2": "Pose de lavabo"},
    )
    assert response["Location"] == url("fin")
    profile = Profile.objects.get(user=new_client.user)
    assert profile.services.count() == 2
    assert profile.bio.startswith("Je répare")
    page = new_client.get(url("fin"))
    assert page.status_code == 200
    body = page.content.decode()
    assert "Ta page est en ligne" in body
    assert f"/{profile.slug}/qr.svg" in body
    assert "wa.me" in body
    profile.refresh_from_db()
    assert profile.onboarding_completed_at is not None


def test_unknown_step_404(new_client):
    assert new_client.get(url("nimporte")).status_code == 404
