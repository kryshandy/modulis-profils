"""Platform-wide dark/light/auto mode integration and CSP compliance."""

from pathlib import Path

import pytest
from django.conf import settings

pytestmark = pytest.mark.django_db


def test_theme_mode_script_exists_and_csp_safe():
    js = Path(settings.BASE_DIR, "static/js/theme-mode.js").read_text(encoding="utf-8")
    assert "modulis-theme" in js
    assert "data-theme" in js
    assert "eval(" not in js


@pytest.mark.parametrize("path", ["/", "/cgu", "/espace/connexion"])
def test_public_and_auth_pages_expose_theme_toggle_and_csp(client, path):
    response = client.get(path)
    assert response.status_code == 200
    body = response.content.decode()
    assert "theme-mode.js" in body
    assert "data-theme-toggle" in body
    assert "color-scheme" in body
    csp = response.headers.get("Content-Security-Policy", "")
    assert "script-src 'self'" in csp


def test_dashboard_exposes_theme_toggle(client):
    from tests.factories import ProfileFactory

    profile = ProfileFactory()
    client.force_login(profile.user)
    response = client.get("/espace/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "theme-mode.js" in body
    assert "data-theme-toggle" in body
