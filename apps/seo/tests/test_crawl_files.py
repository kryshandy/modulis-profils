"""robots.txt, sitemaps and the IndexNow key file."""

import re

import pytest
from django.test import override_settings

from apps.profiles.models import Profile
from apps.seo.tests.utils import indexable_profile
from apps.seo.views import robots_lines
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

KEY = "a1b2c3d4e5f6a7b8c9d0"


def test_robots_txt(client):
    response = client.get("/robots.txt")
    body = response.content.decode()
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    lines = body.splitlines()
    assert "User-agent: *" in lines
    assert "Disallow: /espace/" in lines
    assert not any("gestion" in line for line in lines)  # the admin URL is secret (ADR-0010)
    assert "Sitemap: https://profils.test/sitemap.xml" in lines
    assert "Disallow: /" not in lines
    assert "Disallow: /c/" not in lines  # Google must see the noindex of /c/


@override_settings(ADMIN_URL="/")
def test_robots_never_disallows_everything():
    assert "Disallow: /" not in robots_lines()


@override_settings(ADMIN_URL="gestion-7k2m9q4x8p3z/")
def test_robots_never_reveals_the_secret_admin_url():
    """Security review 2026-11-11: robots.txt is public, the admin address must stay secret."""
    assert not any("7k2m9q4x8p3z" in line for line in robots_lines())


def test_sitemap_index_lists_sections(client, settings):
    for _ in range(settings.SEO_DIRECTORY_MIN_PROFILES):
        indexable_profile()
    response = client.get("/sitemap.xml")
    body = response.content.decode()
    assert response.status_code == 200
    for section in ("profils", "annuaire", "pages"):
        assert f"<loc>https://profils.test/sitemap-{section}.xml</loc>" in body


def test_sitemap_index_omits_empty_sections(client):
    indexable_profile()  # below the directory threshold: the « annuaire » section is empty
    body = client.get("/sitemap.xml").content.decode()
    assert "sitemap-profils.xml" in body
    assert "sitemap-pages.xml" in body
    assert "sitemap-annuaire.xml" not in body


def test_sitemap_lastmod_is_full_w3c_datetime(client):
    profile = indexable_profile()
    body = client.get("/sitemap-profils.xml").content.decode()
    (lastmod,) = re.findall(r"<lastmod>(.*?)</lastmod>", body)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", lastmod), lastmod
    from datetime import datetime

    assert datetime.fromisoformat(lastmod) == profile.content_updated_at.replace(microsecond=0)


def test_robots_disallows_tracking_endpoints(client):
    lines = client.get("/robots.txt").content.decode().splitlines()
    assert "Disallow: /p/" in lines
    assert "Disallow: /a/" in lines


def test_profile_sitemap_lists_only_indexable_profiles(client):
    good = indexable_profile()
    thin = ProfileFactory()
    private = indexable_profile()
    Profile.objects.filter(pk=private.pk).update(visibility=Profile.Visibility.PRIVATE)
    suspended = indexable_profile()
    Profile.objects.filter(pk=suspended.pk).update(status=Profile.Status.SUSPENDED)
    response = client.get("/sitemap-profils.xml", HTTP_HOST="localhost")
    body = response.content.decode()
    assert response.status_code == 200
    assert response["X-Robots-Tag"].startswith("noindex")
    locs = re.findall(r"<loc>(.*?)</loc>", body)
    assert locs == [f"https://profils.test/{good.slug}"]
    assert f"<lastmod>{good.content_updated_at.date().isoformat()}" in body
    assert thin.slug not in body


def test_unknown_sitemap_section_is_404(client):
    assert client.get("/sitemap-inconnu.xml").status_code == 404


def test_directory_sitemap_respects_threshold(client, settings):
    for _ in range(settings.SEO_DIRECTORY_MIN_PROFILES - 1):
        indexable_profile()
    assert "plombiers/douala" not in client.get("/sitemap-annuaire.xml").content.decode()


def test_directory_sitemap_lists_pages_meeting_threshold(client, settings):
    for _ in range(settings.SEO_DIRECTORY_MIN_PROFILES):
        indexable_profile()
    body = client.get("/sitemap-annuaire.xml").content.decode()
    assert "<loc>https://profils.test/plombiers/douala</loc>" in body
    assert "<loc>https://profils.test/villes/douala</loc>" in body
    assert "<lastmod>" in body


def test_pages_sitemap(client):
    assert "<loc>https://profils.test/</loc>" in client.get("/sitemap-pages.xml").content.decode()


@override_settings(KLIZ_INDEXNOW_KEY=KEY)
def test_indexnow_key_file(client):
    response = client.get(f"/{KEY}.txt")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert response.content.decode() == KEY
    assert client.get("/zzzzzzzzzzzz.txt").status_code == 404


@override_settings(KLIZ_INDEXNOW_KEY="")
def test_indexnow_key_file_absent_when_not_configured(client):
    assert client.get(f"/{KEY}.txt").status_code == 404


@override_settings(KLIZ_INDEXNOW_KEY="bad key!")
def test_indexnow_key_file_rejects_invalid_setting(client):
    assert client.get("/bad-key.txt").status_code == 404


def test_crawl_files_root_segments_are_reserved():
    from apps.profiles.services import SYSTEM_RESERVED_SLUGS

    assert {"robots", "sitemap"} <= SYSTEM_RESERVED_SLUGS
