import pytest

from apps.platform import services
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def maintenance():
    services.update_settings(None, "maintenance", {"maintenance_mode": True, "maintenance_message": "Pause café"})


def test_off_by_default_public_pages_served(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/robots.txt").status_code == 200


def test_public_request_gets_branded_503(client, maintenance):
    response = client.get("/")
    assert response.status_code == 503
    assert response["Retry-After"] == "600"
    assert "noindex" in response["X-Robots-Tag"]
    assert response["Cache-Control"] == "no-store"
    content = response.content.decode()
    assert "Pause café" in content
    assert 'name="robots" content="noindex' in content


def test_any_public_url_blocked(client, maintenance, profile):
    assert client.get(f"/{profile.slug}").status_code == 503
    assert client.get("/espace/").status_code == 503


def test_logged_in_pro_is_blocked_too(client, maintenance, profile):
    client.force_login(profile.user)
    assert client.get("/").status_code == 503


def test_staff_bypass(client, maintenance):
    client.force_login(UserFactory(is_staff=True))
    assert client.get("/").status_code != 503


@pytest.mark.parametrize("path", ["/gestion/login/", "/gestion/", "/healthz", "/robots.txt", "/static/css/app.css"])
def test_infrastructure_paths_bypass(client, maintenance, path):
    assert client.get(path).status_code != 503


def test_admin_login_page_reachable(client, maintenance):
    assert client.get("/gestion/login/").status_code == 200


def test_switching_off_restores_site_immediately(client, maintenance):
    assert client.get("/").status_code == 503
    services.update_settings(None, "maintenance", {"maintenance_mode": False})
    assert client.get("/").status_code != 503
