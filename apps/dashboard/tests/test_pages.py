import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.cards.models import Card
from apps.profiles.models import Profile, SlugRegistry
from tests.factories import CardFactory, ProfileFactory, make_complete_profile

pytestmark = pytest.mark.django_db


class TestHome:
    def test_home_shows_url_gauge_checklist_and_plan(self, logged_client, profile):
        body = logged_client.get(reverse("dashboard:home")).content.decode()
        assert profile.slug in body
        assert "gauge__ring" in body
        assert reverse("dashboard:edit", kwargs={"section": "presentation"}) in body
        assert "Offre gratuite" in body
        assert "Pas encore sur Google" in body
        assert 'data-tour="7"' in body

    def test_indexable_profile_visible_on_google(self, client):
        profile = make_complete_profile(photo="p.webp")
        from apps.profiles.services import refresh_seo_state

        refresh_seo_state(profile)
        client.force_login(profile.user)
        assert "Visible sur Google" in client.get(reverse("dashboard:home")).content.decode()

    def test_no_profile_redirects_to_onboarding(self, client, user):
        client.force_login(user)
        assert client.get(reverse("dashboard:home"))["Location"] == reverse(
            "dashboard:onboarding", kwargs={"step": "nom"}
        )

    def test_tour_autostart_only_after_onboarding_until_done(self, logged_client, profile):
        assert 'data-tour-autostart="1"' not in logged_client.get(reverse("dashboard:home")).content.decode()
        Profile.objects.filter(pk=profile.pk).update(onboarding_completed_at=timezone.now())
        assert 'data-tour-autostart="1"' in logged_client.get(reverse("dashboard:home")).content.decode()
        response = logged_client.post(reverse("dashboard:tour_done"), HTTP_X_REQUESTED_WITH="fetch")
        assert response.status_code == 204
        profile.refresh_from_db()
        assert profile.tour_completed_at is not None
        assert 'data-tour-autostart="1"' not in logged_client.get(reverse("dashboard:home")).content.decode()
        assert 'data-tour-autostart="1"' in logged_client.get(reverse("dashboard:home") + "?visite=1").content.decode()

    def test_tour_done_post_only(self, logged_client):
        assert logged_client.get(reverse("dashboard:tour_done")).status_code == 405


class TestSwitcher:
    def test_switch_between_own_profiles(self, logged_client, profile):
        other = ProfileFactory(user=profile.user, display_name="Deuxième Boutique")
        body = logged_client.get(reverse("dashboard:home")).content.decode()
        assert 'name="profile_id"' in body
        logged_client.post(reverse("dashboard:switch_profile"), {"profile_id": other.pk})
        assert logged_client.session["dashboard_profile_id"] == other.pk
        assert "Bonjour Deuxième Boutique" in logged_client.get(reverse("dashboard:home")).content.decode()

    def test_no_switcher_with_one_profile(self, logged_client):
        assert 'name="profile_id"' not in logged_client.get(reverse("dashboard:home")).content.decode()


class TestShareStatsHelp:
    def test_share_page(self, logged_client, profile):
        body = logged_client.get(reverse("dashboard:share")).content.decode()
        assert f"/{profile.slug}/qr.png" in body
        assert f"/{profile.slug}/qr.svg" in body
        assert "https://wa.me/?text=" in body

    def test_poster(self, logged_client, profile):
        body = logged_client.get(reverse("dashboard:poster")).content.decode()
        assert profile.display_name in body

    def test_stats_placeholder_or_data(self, logged_client):
        assert logged_client.get(reverse("dashboard:stats")).status_code == 200

    def test_help(self, logged_client):
        body = logged_client.get(reverse("dashboard:help")).content.decode()
        assert "Revoir la visite guidée" in body
        assert "<details>" in body


class TestCards:
    def test_link_card(self, logged_client, profile):
        card = CardFactory(public_code="TSTAB23")
        response = logged_client.post(
            reverse("dashboard:card_link"), {"public_code": "tstab23", "activation_code": "abcd-2345"}
        )
        assert response.status_code == 302
        card.refresh_from_db()
        assert card.status == Card.Status.ACTIVE
        assert card.profile == profile
        assert "TSTAB23" in logged_client.get(reverse("dashboard:cards")).content.decode()

    def test_wrong_activation_code_is_recorded(self, logged_client):
        card = CardFactory(public_code="TSTAB24")
        response = logged_client.post(
            reverse("dashboard:card_link"), {"public_code": "TSTAB24", "activation_code": "WRONG999"}
        )
        assert response.status_code == 200
        assert "ne correspond pas" in response.content.decode()
        assert card.activation_attempts.filter(success=False).count() == 1
        card.refresh_from_db()
        assert card.status == Card.Status.STOCK

    def test_unknown_card(self, logged_client):
        response = logged_client.post(
            reverse("dashboard:card_link"), {"public_code": "ZZZZZZZ", "activation_code": "X"}
        )
        assert "Aucune carte" in response.content.decode()

    def test_already_active_card_error(self, logged_client):
        CardFactory(public_code="TSTAB25", status=Card.Status.ACTIVE, profile=ProfileFactory())
        response = logged_client.post(
            reverse("dashboard:card_link"), {"public_code": "TSTAB25", "activation_code": "ABCD2345"}
        )
        assert "déjà activée" in response.content.decode()

    def test_report_lost(self, logged_client, profile):
        card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
        logged_client.post(reverse("dashboard:card_lost", args=[card.pk]))
        card.refresh_from_db()
        assert card.status == Card.Status.DISABLED
        assert card.disabled_reason == "lost"


class TestSettings:
    def test_slug_availability_endpoint(self, logged_client, profile):
        check = reverse("dashboard:slug_check")
        ProfileFactory(slug="deja-pris")
        assert "slug-status--ok" in logged_client.get(check, {"slug": "awa-couture-akwa"}).content.decode()
        assert "déjà prise" in logged_client.get(check, {"slug": "deja-pris"}).content.decode()
        assert "3 à 50" in logged_client.get(check, {"slug": "A!"}).content.decode()
        assert "générique" in logged_client.get(check, {"slug": "zebulon"}).content.decode()
        assert "actuelle" in logged_client.get(check, {"slug": profile.slug}).content.decode()

    def test_slug_check_rate_limited(self, logged_client):
        check = reverse("dashboard:slug_check")
        for _ in range(60):
            logged_client.get(check, {"slug": "abc-def"})
        assert "Doucement" in logged_client.get(check, {"slug": "abc-def"}).content.decode()

    def test_change_slug(self, logged_client, profile):
        old = profile.slug
        response = logged_client.post(reverse("dashboard:settings"), {"action": "slug", "slug": "Awa-Couture-Akwa"})
        assert response.status_code == 302
        profile.refresh_from_db()
        assert profile.slug == "awa-couture-akwa"
        assert SlugRegistry.objects.get(slug=old).kind == "old"

    def test_change_slug_error_shown(self, logged_client):
        ProfileFactory(slug="deja-pris")
        response = logged_client.post(reverse("dashboard:settings"), {"action": "slug", "slug": "deja-pris"})
        assert response.status_code == 200
        assert "déjà prise" in response.content.decode()

    def test_language_and_email(self, logged_client, profile):
        logged_client.post(reverse("dashboard:settings"), {"action": "language", "language": "en"})
        logged_client.post(reverse("dashboard:settings"), {"action": "email", "email": "awa@exemple.test"})
        profile.refresh_from_db()
        profile.user.refresh_from_db()
        assert profile.language == "en"
        assert profile.user.email == "awa@exemple.test"

    def test_delete_requires_typed_confirmation(self, logged_client, profile):
        response = logged_client.post(reverse("dashboard:settings"), {"action": "delete", "confirm": "oui"})
        assert response.status_code == 200
        profile.refresh_from_db()
        assert profile.status == Profile.Status.ACTIVE

    def test_delete_page_then_logout(self, logged_client, profile):
        card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
        slug = profile.slug
        response = logged_client.post(reverse("dashboard:settings"), {"action": "delete", "confirm": slug})
        assert response["Location"] == reverse("dashboard:login")
        profile.refresh_from_db()
        assert profile.status == Profile.Status.DELETED
        card.refresh_from_db()
        assert card.status == Card.Status.DISABLED
        assert "_auth_user_id" not in logged_client.session
        assert get_user_model().objects.filter(pk=profile.user_id).exists()
