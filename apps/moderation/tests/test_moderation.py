import pytest
from django.urls import reverse

from apps.moderation import services
from apps.moderation.models import Report
from apps.profiles import services as profile_services
from apps.profiles.models import Profile
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


class TestReportView:
    def test_get_form(self, client):
        profile = ProfileFactory()
        response = client.get(reverse("moderation:report", args=[profile.slug]))
        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="reason"' in content and profile.display_name in content
        assert "noindex" in response["X-Robots-Tag"]

    def test_url(self):
        assert reverse("moderation:report", args=["paul-plombier"]) == "/signaler/paul-plombier"

    def test_submit_creates_report_and_redirects(self, client):
        profile = ProfileFactory()
        response = client.post(
            reverse("moderation:report", args=[profile.slug]),
            {"reason": "scam", "message": "Il demande une avance puis disparaît.", "contact": "+237690000099"},
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("moderation:report_thanks", args=[profile.slug])
        report = Report.objects.get()
        assert report.profile == profile and report.reason == "scam" and report.status == Report.Status.OPEN
        assert report.reporter_contact == "+237690000099" and len(report.reporter_ip_hash) == 32
        assert client.get(response["Location"]).status_code == 200

    def test_invalid_reason_rerenders(self, client):
        profile = ProfileFactory()
        response = client.post(reverse("moderation:report", args=[profile.slug]), {"reason": "nope"})
        assert response.status_code == 200
        assert not Report.objects.exists()

    def test_honeypot_silently_dropped(self, client):
        profile = ProfileFactory()
        response = client.post(
            reverse("moderation:report", args=[profile.slug]), {"reason": "spam", "website": "http://spam.test"}
        )
        assert response.status_code == 302
        assert not Report.objects.exists()

    def test_unknown_private_suspended_404(self, client):
        private = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
        suspended = ProfileFactory(status=Profile.Status.SUSPENDED)
        for slug in ("inconnu-total", private.slug, suspended.slug):
            assert client.get(reverse("moderation:report", args=[slug])).status_code == 404

    def test_old_slug_still_reportable(self, client):
        profile = ProfileFactory(slug="ancien-nom-pro")
        profile_services.change_slug(profile, "nouveau-nom-pro")
        response = client.post(reverse("moderation:report", args=["ancien-nom-pro"]), {"reason": "spam"})
        assert response.status_code == 302
        assert Report.objects.get().profile == profile

    def test_rate_limited(self, client):
        profile = ProfileFactory()
        url = reverse("moderation:report", args=[profile.slug])
        statuses = [client.post(url, {"reason": "spam"}).status_code for _ in range(6)]
        assert statuses[:5] == [302] * 5 and statuses[5] == 429
        assert Report.objects.count() == 5


class TestServices:
    def test_suspend_closes_all_open_reports(self, admin_user):
        profile = ProfileFactory()
        first = services.create_report(profile, "scam")
        second = services.create_report(profile, "spam")
        other = services.create_report(ProfileFactory(), "spam")
        services.suspend_reported_profile(first, by=admin_user)
        profile.refresh_from_db()
        assert profile.status == Profile.Status.SUSPENDED and "signalement" in profile.suspended_reason
        for report in (first, second):
            report.refresh_from_db()
            assert report.status == Report.Status.ACTIONED and report.handled_by == admin_user and report.handled_at
        other.refresh_from_db()
        assert other.status == Report.Status.OPEN
        assert services.open_reports_count() == 1


class TestReportAdmin:
    def _action(self, admin_client, action, reports):
        return admin_client.post(
            reverse("admin:moderation_report_changelist"),
            {"action": action, "_selected_action": [r.pk for r in reports]},
        )

    def test_suspend_action(self, admin_client, admin_user):
        profile = ProfileFactory()
        report = services.create_report(profile, "scam")
        response = self._action(admin_client, "suspend_profile", [report])
        assert response.status_code == 302
        profile.refresh_from_db()
        report.refresh_from_db()
        assert profile.status == Profile.Status.SUSPENDED
        assert report.status == Report.Status.ACTIONED and report.handled_by == admin_user

    def test_dismiss_and_actioned_actions(self, admin_client, admin_user):
        a = services.create_report(ProfileFactory(), "spam")
        b = services.create_report(ProfileFactory(), "other")
        self._action(admin_client, "dismiss", [a])
        self._action(admin_client, "mark_actioned", [b])
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.status == Report.Status.DISMISSED and a.handled_by == admin_user
        assert b.status == Report.Status.ACTIONED and b.handled_at
        assert a.profile.status == Profile.Status.ACTIVE

    def test_manual_status_change_sets_handler(self, admin_client, admin_user):
        report = services.create_report(ProfileFactory(), "spam")
        response = admin_client.post(
            reverse("admin:moderation_report_change", args=[report.pk]),
            {"status": "dismissed", "resolution_note": "Doublon"},
        )
        assert response.status_code == 302
        report.refresh_from_db()
        assert report.status == "dismissed" and report.handled_by == admin_user and report.resolution_note == "Doublon"
