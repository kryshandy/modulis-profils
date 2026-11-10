"""Home, city pages and trade×city directory pages (plan §6.9)."""

import pytest
from django.test import override_settings

from apps.seo.tests.utils import graph_node, indexable_profile, meta_content
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def test_home_renders(client):
    profile = indexable_profile()
    response = client.get("/")
    body = response.content.decode()
    assert response.status_code == 200
    assert "Crée ta page pro gratuite" in body
    assert meta_content(body, "name", "robots") == "index, follow"
    assert '<link rel="canonical" href="https://profils.test/">' in body
    assert f'href="/{profile.slug}"' in body
    assert "Douala" in body
    assert graph_node(body, "WebSite")["name"] == "Modulis Profils"


def test_home_does_not_list_non_indexable_profiles(client):
    profile = ProfileFactory()
    assert f'href="/{profile.slug}"' not in client.get("/").content.decode()


def test_directory_below_threshold_is_noindex(client):
    indexable_profile()
    response = client.get("/plombiers/douala")
    assert response.status_code == 200
    assert meta_content(response.content.decode(), "name", "robots") == "noindex, follow"


def test_directory_at_threshold_is_indexable(client, settings):
    profiles = [indexable_profile() for _ in range(settings.SEO_DIRECTORY_MIN_PROFILES)]
    response = client.get("/plombiers/douala")
    body = response.content.decode()
    assert response.status_code == 200
    assert meta_content(body, "name", "robots") == "index, follow"
    assert '<link rel="canonical" href="https://profils.test/plombiers/douala">' in body
    assert "<h1>Plombiers à Douala</h1>" in body
    for profile in profiles:
        assert f'href="/{profile.slug}"' in body
    crumbs = graph_node(body, "BreadcrumbList")
    assert [i["name"] for i in crumbs["itemListElement"]] == ["Accueil", "Douala", "Plombiers à Douala"]


def test_directory_unknown_trade_or_city_is_404(client):
    assert client.get("/inconnus/douala").status_code == 404
    assert client.get("/plombiers/nulle-part").status_code == 404


@override_settings(SEO_DIRECTORY_MIN_PROFILES=1)
def test_directory_pagination_self_canonical(client, monkeypatch):
    monkeypatch.setattr("apps.public.views.DIRECTORY_PAGE_SIZE", 2)
    for _ in range(3):
        indexable_profile()
    first = client.get("/plombiers/douala").content.decode()
    assert 'rel="next" href="?page=2"' in first
    response = client.get("/plombiers/douala?page=2")
    body = response.content.decode()
    assert response.status_code == 200
    assert '<link rel="canonical" href="https://profils.test/plombiers/douala?page=2">' in body
    assert meta_content(body, "name", "robots") == "index, follow"
    assert client.get("/plombiers/douala?page=3").status_code == 404
    assert client.get("/plombiers/douala?page=abc").status_code == 404
    assert client.get("/plombiers/douala?page=0").status_code == 404


def test_city_page(client, settings):
    indexable_profile()
    response = client.get("/villes/douala")
    body = response.content.decode()
    assert response.status_code == 200
    assert meta_content(body, "name", "robots") == "noindex, follow"
    assert "Plombiers" in body
    for _ in range(settings.SEO_DIRECTORY_MIN_PROFILES - 1):
        indexable_profile()
    body = client.get("/villes/douala").content.decode()
    assert meta_content(body, "name", "robots") == "index, follow"
    assert 'href="/plombiers/douala"' in body


def test_city_unknown_is_404(client):
    assert client.get("/villes/atlantide").status_code == 404


def test_404_page_is_noindex(client):
    response = client.get("/personne-inconnue")
    assert response.status_code == 404
    assert meta_content(response.content.decode(), "name", "robots") == "noindex, follow"
