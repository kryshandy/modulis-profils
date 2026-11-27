import pytest
from django.urls import reverse

from apps.billing.models import Plan, Subscription
from apps.billing.services import current_plan_code, grant_plan
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


class TestBillingUI:
    def test_requires_login(self, client):
        response = client.get(reverse("dashboard:billing"))
        assert response.status_code == 302
        assert reverse("dashboard:login") in response["Location"]

    def test_displays_current_plan_and_public_plans_with_xaf_prices(self, logged_client, profile):
        response = logged_client.get(reverse("dashboard:billing"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "Offre &amp; Abonnement" in body or "Offre & Abonnement" in body
        assert "Gratuit" in body
        assert "Essentiel" in body
        assert "Pro" in body
        assert "Équipe" in body
        assert "XAF" in body
        assert "12" in body and "30" in body

    def test_post_switches_plan_and_grants_subscription(self, logged_client, profile):
        assert current_plan_code(profile) == Plan.Code.FREE
        response = logged_client.post(
            reverse("dashboard:billing"),
            {"plan_code": Plan.Code.ESSENTIEL},
            follow=True,
        )
        assert response.status_code == 200
        assert current_plan_code(profile) == Plan.Code.ESSENTIEL
        body = response.content.decode()
        assert "Essentiel" in body
        assert "activée" in body

    def test_post_same_plan_does_not_duplicate_subscription(self, logged_client, profile):
        pro = Plan.objects.get(code=Plan.Code.PRO)
        grant_plan(profile, pro)
        initial_count = Subscription.objects.filter(profile=profile).count()

        response = logged_client.post(
            reverse("dashboard:billing"),
            {"plan_code": Plan.Code.PRO},
            follow=True,
        )
        assert response.status_code == 200
        assert Subscription.objects.filter(profile=profile).count() == initial_count
        assert "déjà" in response.content.decode()

    def test_post_invalid_plan_shows_error(self, logged_client, profile):
        response = logged_client.post(
            reverse("dashboard:billing"),
            {"plan_code": "inexistant"},
            follow=True,
        )
        assert response.status_code == 200
        assert current_plan_code(profile) == Plan.Code.FREE

    def test_idor_cannot_change_other_users_profile_plan(self, logged_client, profile):
        other_profile = ProfileFactory()
        response = logged_client.post(
            reverse("dashboard:billing"),
            {"plan_code": Plan.Code.PRO, "profile_id": other_profile.pk},
        )
        assert response.status_code == 302
        assert current_plan_code(other_profile) == Plan.Code.FREE
        assert current_plan_code(profile) == Plan.Code.PRO

    def test_suspended_profile_cannot_post_plan_change(self, logged_client, profile):
        profile.status = profile.Status.SUSPENDED
        profile.save(update_fields=["status"])
        response = logged_client.post(
            reverse("dashboard:billing"),
            {"plan_code": Plan.Code.ESSENTIEL},
        )
        assert response.status_code == 403
        assert current_plan_code(profile) == Plan.Code.FREE
