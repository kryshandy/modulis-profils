"""Modulis identity: brand head (favicons, manifest, self-hosted font), announcement banner, templates entry points."""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.db import DatabaseError
from django.template import Context, Template
from django.urls import reverse

from apps.platform.services import get_settings

pytestmark = pytest.mark.django_db

STATIC = Path(settings.BASE_DIR) / "static"


def set_announcement(text: str) -> None:
    obj = get_settings()
    obj.announcement = text
    obj.save()  # invalidates the settings cache


def render_tag() -> str:
    return Template("{% load brand_tags %}{% platform_announcement as a %}[{{ a }}]").render(Context())


class TestAnnouncementTag:
    def test_empty_by_default(self):
        assert render_tag() == "[]"

    def test_returns_the_control_center_text(self):
        set_announcement("  Maintenance dimanche à 22 h  ")
        assert render_tag() == "[Maintenance dimanche à 22 h]"

    def test_database_error_degrades_to_empty(self, monkeypatch):
        def broken():
            raise DatabaseError("no such table")

        monkeypatch.setattr("apps.platform.services.get_settings", broken)
        assert render_tag() == "[]"

    def test_text_is_escaped(self):
        set_announcement("<b>x</b>")
        assert render_tag() == "[&lt;b&gt;x&lt;/b&gt;]"


class TestDashboardShell:
    def test_banner_shown_in_dashboard(self, logged_client):
        set_announcement("Nouveaux modèles disponibles")
        body = logged_client.get(reverse("dashboard:home")).content.decode()
        assert '<p class="announce" role="status">' in body
        assert "Nouveaux modèles disponibles" in body

    def test_no_banner_when_empty(self, logged_client):
        assert 'class="announce"' not in logged_client.get(reverse("dashboard:home")).content.decode()

    def test_templates_entry_points(self, logged_client):
        body = logged_client.get(reverse("dashboard:home")).content.decode()
        # sidebar + "Plus" sheet + home tile
        assert body.count('href="/espace/modeles/"') == 3
        assert "Choisis ton modèle de site" in body
        assert 'class="promo"' in body

    def test_brand_lockup_in_shell(self, logged_client):
        body = logged_client.get(reverse("dashboard:home")).content.decode()
        assert 'class="brand sidenav__brand"' in body
        assert "Modulis Tech" in body


class TestBrandHead:
    def test_base_links_favicons_manifest_and_font(self, client):
        body = client.get(reverse("dashboard:login")).content.decode()
        assert '<link rel="icon" href="/static/img/brand/favicon.svg" type="image/svg+xml">' in body
        assert 'href="/static/img/brand/favicon-32.png"' in body
        assert '<link rel="apple-touch-icon" href="/static/img/brand/apple-touch-icon.png">' in body
        assert '<link rel="manifest" href="/static/site.webmanifest">' in body
        assert '<link rel="stylesheet" href="/static/css/fonts.css">' in body
        preload = '<link rel="preload" href="/static/fonts/archivo-variable.woff2" as="font" type="font/woff2"'
        assert f"{preload} crossorigin>" in body
        # fonts before the design system, nothing loaded from a third party
        assert body.index("css/fonts.css") < body.index("css/app.css")
        assert "fonts.googleapis.com" not in body and "fonts.gstatic.com" not in body

    def test_platform_home_uses_brand_and_platform_css(self, client):
        body = client.get("/").content.decode()
        assert 'href="/static/css/platform.css"' in body
        assert "css/profile.css" not in body  # the pros' stylesheet is not needed here
        assert 'href="/static/img/brand/favicon.svg"' in body
        assert body.count("<h1") == 1
        assert "Une solution" in body and "Modulis Tech" in body
        assert "/espace/connexion?next=/espace/modeles/" in body


class TestBrandAssets:
    def test_font_files_are_woff2_and_licensed(self):
        for name in ("archivo-variable.woff2", "archivo-variable-latin.woff2", "archivo-variable-latin-ext.woff2"):
            assert (STATIC / "fonts" / name).read_bytes()[:4] == b"wOF2", name
        assert "SIL Open Font License" in (STATIC / "fonts" / "OFL.txt").read_text()
        css = (STATIC / "css" / "fonts.css").read_text()
        assert "font-display: swap" in css and "unicode-range" in css
        assert "../fonts/archivo-variable.woff2" in css

    def test_manifest_icons_exist_with_their_size(self):
        from PIL import Image

        manifest = json.loads((STATIC / "site.webmanifest").read_text())
        assert manifest["start_url"] == "/espace/"
        purposes = set()
        for icon in manifest["icons"]:
            path = STATIC / icon["src"]
            assert path.exists(), icon["src"]
            purposes.add(icon.get("purpose", "any"))
            if icon["type"] == "image/png":
                width, height = (int(n) for n in icon["sizes"].split("x"))
                with Image.open(path) as image:
                    assert image.size == (width, height)
        assert "maskable" in purposes

    def test_brand_images(self):
        from PIL import Image

        with Image.open(STATIC / "img/brand/apple-touch-icon.png") as image:
            assert image.size == (180, 180)
        with Image.open(STATIC / "img/brand/favicon-32.png") as image:
            assert image.size == (32, 32)
        for name in ("logo-mark.svg", "favicon.svg", "logo-full.svg", "logo-full-light.svg"):
            assert (STATIC / "img/brand" / name).read_text().startswith("<svg"), name

    def test_app_css_budget(self):
        assert (STATIC / "css" / "app.css").stat().st_size <= 60 * 1024
