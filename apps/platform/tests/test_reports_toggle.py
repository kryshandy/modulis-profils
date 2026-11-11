import pytest
from django.urls import reverse

from apps.moderation.models import Report
from apps.platform import services

pytestmark = pytest.mark.django_db


def test_report_form_open_by_default(client, profile):
    response = client.get(reverse("moderation:report", args=[profile.slug]))
    assert response.status_code == 200
    assert "Envoyer le signalement" in response.content.decode()


def test_reports_switched_off_shows_closed_message(client, profile):
    services.update_settings(None, "reports", {"reports_enabled": False})
    url = reverse("moderation:report", args=[profile.slug])
    response = client.get(url)
    assert response.status_code == 200
    assert "noindex" in response["X-Robots-Tag"]
    content = response.content.decode()
    assert "momentanément" in content
    assert "Envoyer le signalement" not in content

    client.post(url, {"reason": "spam", "message": "x"})
    assert not Report.objects.exists()


def test_reports_closed_unknown_slug_still_404(client, db):
    services.update_settings(None, "reports", {"reports_enabled": False})
    assert client.get(reverse("moderation:report", args=["inconnu-xyz"])).status_code == 404
