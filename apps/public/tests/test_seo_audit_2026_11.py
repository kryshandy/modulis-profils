"""SEO audit of 2026-11-10: regression tests for every fix on the public pages."""

import re
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import modify_settings

from apps.profiles.models import Profile
from apps.profiles.services import delete_profile
from apps.seo import jsonld
from apps.seo.tests.utils import graph_node, indexable_profile, jsonld_graph, meta_content
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

PUBLIC_HEADERS = modify_settings(MIDDLEWARE={"prepend": "apps.public.middleware.PublicHeadersMiddleware"})


def body_of(client, path, **kwargs):
    response = client.get(path, **kwargs)
    return response, response.content.decode()


def fill_directory(settings, n=None):
    return [indexable_profile() for _ in range(n or settings.SEO_DIRECTORY_MIN_PROFILES)]


def with_photo(profile, name="photo.webp"):
    Profile.objects.filter(pk=profile.pk).update(photo=f"profiles/{profile.pk}/{name}")
    profile.refresh_from_db()
    return profile


@pytest.fixture
def variants(monkeypatch):
    """Fake apps.profiles.services.image_variants (contract of the backend agent)."""

    def image_variants(fieldfile):
        base = fieldfile.url.rsplit(".", 1)[0]
        return [(f"{base}-{w}.webp", w) for w in (160, 400, 800)]

    monkeypatch.setattr("apps.profiles.services.image_variants", image_variants, raising=False)


# --- 1. JSON-LD image ------------------------------------------------------------------------


def test_jsonld_image_is_the_real_photo_only(client):
    profile = indexable_profile()
    _, body = body_of(client, f"/{profile.slug}")
    entity = graph_node(body, "Plumber")
    assert "image" not in entity  # never og.png (noindex)
    assert "og.png" not in str(jsonld_graph(body))
    with_photo(profile)
    _, body = body_of(client, f"/{profile.slug}")
    assert graph_node(body, "Plumber")["image"] == f"https://profils.test/media/profiles/{profile.pk}/photo.webp"


# --- 3. soft 404 and breadcrumb threshold ----------------------------------------------------


def test_empty_listing_pages_are_404(client):
    ProfileFactory()  # exists but not indexable
    assert client.get("/villes/douala").status_code == 404
    assert client.get("/plombiers/douala").status_code == 404


def test_listing_below_threshold_is_200_noindex_and_breadcrumb_not_linked(client):
    profile = indexable_profile()
    response, body = body_of(client, "/plombiers/douala")
    assert response.status_code == 200
    assert meta_content(body, "name", "robots") == "noindex, follow"
    assert 'href="/villes/douala"' not in body  # the city page is noindex too
    crumbs = graph_node(body, "BreadcrumbList")
    assert [i["name"] for i in crumbs["itemListElement"]] == ["Accueil", "Plombiers à Douala"]
    _, body = body_of(client, f"/{profile.slug}")
    nav = re.search(r'<nav class="breadcrumb".*?</nav>', body, re.S).group(0)
    assert "<span>Douala</span>" in nav
    assert 'href="/villes/douala"' not in nav
    assert 'href="/plombiers/douala"' not in nav
    names = [i["name"] for i in graph_node(body, "BreadcrumbList")["itemListElement"]]
    assert names == ["Accueil", profile.display_name]
    assert all("item" in i for i in graph_node(body, "BreadcrumbList")["itemListElement"])


def test_breadcrumb_linked_at_threshold(client, settings):
    profile, *_ = fill_directory(settings)
    _, body = body_of(client, f"/{profile.slug}")
    nav = re.search(r'<nav class="breadcrumb".*?</nav>', body, re.S).group(0)
    assert 'href="/villes/douala"' in nav
    assert 'href="/plombiers/douala"' in nav
    _, body = body_of(client, "/plombiers/douala")
    assert 'href="/villes/douala"' in body


# --- 4. trailing slash on listing pages ------------------------------------------------------


def test_listing_trailing_slash_redirects(client):
    indexable_profile()
    response = client.get("/villes/douala/")
    assert (response.status_code, response["Location"]) == (301, "/villes/douala")
    response = client.get("/plombiers/douala/?page=2")
    assert (response.status_code, response["Location"]) == (301, "/plombiers/douala?page=2")
    assert client.get("/villes/atlantide/").status_code == 404
    assert client.get("/inconnus/douala/").status_code == 404


# --- 5. @graph and LocalBusiness richness ----------------------------------------------------


def assert_graph_valid(body):
    graph = jsonld_graph(body)
    assert jsonld.unresolved_refs({"@graph": graph}) == []
    ids = [node["@id"] for node in graph]
    assert len(ids) == len(set(ids))
    types = {node["@type"] for node in graph}
    assert {"WebSite", "Organization"} <= types
    website = graph_node(body, "WebSite")
    assert website["publisher"] == {"@id": "https://profils.test/#organization"}
    org = graph_node(body, "Organization")
    assert org["name"] == "Modulis Tech"
    assert org["logo"]["url"] == "https://profils.test/static/img/logo.png"
    return graph


def test_profile_graph_is_linked(client, settings):
    profile, *_ = fill_directory(settings)
    _, body = body_of(client, f"/{profile.slug}")
    assert_graph_valid(body)
    page = graph_node(body, "WebPage")
    assert page["url"] == f"https://profils.test/{profile.slug}"
    assert page["inLanguage"] == "fr"
    assert page["mainEntity"] == {"@id": f"https://profils.test/{profile.slug}#business"}
    assert page["breadcrumb"] == {"@id": f"https://profils.test/{profile.slug}#breadcrumb"}


def test_listing_and_home_graphs_are_linked(client, settings):
    profiles = fill_directory(settings)
    for path in ("/", "/villes/douala", "/plombiers/douala"):
        _, body = body_of(client, path)
        assert_graph_valid(body)
    item_list = graph_node(body, "ItemList")
    assert {i["url"] for i in item_list["itemListElement"]} == {f"https://profils.test/{p.slug}" for p in profiles}
    assert graph_node(body, "CollectionPage")["mainEntity"] == {"@id": item_list["@id"]}


def test_jsonld_graph_escapes_user_input(client):
    profile = indexable_profile(display_name="Tom & Jerry > Co")
    _, body = body_of(client, f"/{profile.slug}")
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S).group(1)
    assert "<" not in raw and ">" not in raw and "&" not in raw
    assert graph_node(body, "Plumber")["name"] == "Tom & Jerry > Co"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("dès 5 000 FCFA", {"minPrice": 5000}),
        ("Dès 5 000 F", {"minPrice": 5000}),
        ("à partir de 12.500 FCFA", {"minPrice": 12500}),
        ("5 000 – 10 000 FCFA", {"minPrice": 5000, "maxPrice": 10000}),
        ("7500 FCFA", {"price": 7500}),
        ("Sur devis", {}),
        ("24h/24", {}),
        ("", {}),
    ],
)
def test_parse_price(label, expected):
    assert jsonld.parse_price(label) == expected


def test_local_business_richness():
    profile = indexable_profile(address="Rue 12, Akwa")
    profile.services.update(price_label="dès 5 000 FCFA")
    profile.latitude, profile.longitude = Decimal("4.051056"), Decimal("9.767869")
    profile.opening_hours = {
        "mo": [["08:00", "18:00"]],
        "tu": [["08:00", "18:00"]],
        "sa": [["09:00", "13:00"], ["bad", "x"]],
        "su": [],
    }
    profile.price_range = "5 000 – 50 000 FCFA"
    entity = jsonld.profile_entity(profile)
    offer = entity["makesOffer"][0]
    assert offer["description"] == "dès 5 000 FCFA"
    assert offer["priceSpecification"] == {"@type": "PriceSpecification", "priceCurrency": "XAF", "minPrice": 5000}
    assert entity["geo"] == {"@type": "GeoCoordinates", "latitude": 4.051056, "longitude": 9.767869}
    assert entity["openingHoursSpecification"] == [
        {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["https://schema.org/Monday", "https://schema.org/Tuesday"],
            "opens": "08:00",
            "closes": "18:00",
        },
        {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["https://schema.org/Saturday"],
            "opens": "09:00",
            "closes": "13:00",
        },
    ]
    assert entity["priceRange"] == "5 000 – 50 000 FCFA"
    assert entity["address"]["streetAddress"] == "Rue 12, Akwa"
    assert "@context" not in entity  # lives inside the page @graph


def test_local_business_without_optional_data():
    profile = indexable_profile()
    profile.latitude = None
    entity = jsonld.profile_entity(profile)
    for key in ("geo", "openingHoursSpecification", "priceRange", "image"):
        assert key not in entity
    profile.latitude, profile.longitude = Decimal("123"), Decimal("9")  # out of range
    assert "geo" not in jsonld.profile_entity(profile)


# --- 6. responsive images --------------------------------------------------------------------


def test_profile_images_without_variants_keep_single_src(client):
    profile = with_photo(indexable_profile())
    _, body = body_of(client, f"/{profile.slug}")
    img = re.search(r'<img class="profile-head__photo"[^>]*>', body).group(0)
    assert f'src="/media/profiles/{profile.pk}/photo.webp"' in img
    assert 'width="160" height="160"' in img
    assert "srcset" not in img


def test_responsive_images_never_load_800_for_small_slots(client, variants):
    profile = with_photo(indexable_profile())
    other = with_photo(indexable_profile(), "other.webp")
    _, body = body_of(client, f"/{profile.slug}")
    avatar = re.search(r'<img class="profile-head__photo"[^>]*>', body).group(0)
    assert f'src="/media/profiles/{profile.pk}/photo-400.webp"' in avatar
    assert "photo-160.webp 160w, " in avatar
    assert "-800" not in avatar
    assert 'sizes="160px" width="160" height="160"' in avatar
    preload = re.search(r'<link rel="preload" as="image"[^>]*>', body).group(0)
    assert 'imagesrcset="' in preload and "-800" not in preload
    thumb = re.search(rf'<img class="pro-card__photo" src="/media/profiles/{other.pk}/[^>]*>', body).group(0)
    assert f'src="/media/profiles/{other.pk}/other-160.webp"' in thumb
    assert f'srcset="/media/profiles/{other.pk}/other-160.webp 160w"' in thumb
    assert 'sizes="56px" width="56" height="56"' in thumb


def test_gallery_srcset_includes_original(client, variants):
    from apps.profiles.models import ProfileMedia

    profile = indexable_profile()
    ProfileMedia.objects.create(profile=profile, image=f"profiles/{profile.pk}/gallery/0.webp", width=1600, height=1200)
    _, body = body_of(client, f"/{profile.slug}")
    img = re.search(r'<img src="/media/profiles/[^"]+gallery[^>]+>', body).group(0)
    assert "0-800.webp 800w" in img
    assert f"/media/profiles/{profile.pk}/gallery/0.webp 1600w" in img
    assert 'width="1600" height="1200"' in img


def test_image_variants_failure_falls_back(client, monkeypatch):
    def broken(fieldfile):
        raise OSError("storage down")

    monkeypatch.setattr("apps.profiles.services.image_variants", broken, raising=False)
    profile = with_photo(indexable_profile())
    response, body = body_of(client, f"/{profile.slug}")
    assert response.status_code == 200
    assert f'src="/media/profiles/{profile.pk}/photo.webp"' in body


# --- 7. Vary and Cache-Control ---------------------------------------------------------------

PUBLIC_CC = {"public", "max-age=300", "s-maxage=600", "stale-while-revalidate=86400"}


def cc(response) -> set[str]:
    return {part.strip() for part in response["Cache-Control"].split(",")}


@PUBLIC_HEADERS
def test_public_pages_do_not_vary_on_accept_language(client, settings):
    profile, *_ = fill_directory(settings)
    for path in ("/", "/villes/douala", "/plombiers/douala", f"/{profile.slug}"):
        response = client.get(path, HTTP_ACCEPT_LANGUAGE="en")
        assert response.status_code == 200
        assert "accept-language" not in response.get("Vary", "").lower(), path
        assert cc(response) == PUBLIC_CC, path
        assert response["Content-Language"] == "fr"


@PUBLIC_HEADERS
def test_english_profile_content_language(client):
    profile = indexable_profile(language="en")
    response = client.get(f"/{profile.slug}", HTTP_ACCEPT_LANGUAGE="fr")
    assert response["Content-Language"] == "en"
    assert "accept-language" not in response.get("Vary", "").lower()


@modify_settings(MIDDLEWARE={"remove": "apps.public.middleware.PublicHeadersMiddleware"})
def test_without_middleware_locale_still_varies(client):
    """Documents why the middleware is wired: LocaleMiddleware adds the header after the view."""
    assert "Accept-Language" in client.get("/").get("Vary", "")


def test_middleware_is_wired_above_locale():
    from django.conf import settings

    mw = settings.MIDDLEWARE
    assert mw.index("apps.public.middleware.PublicHeadersMiddleware") < mw.index(
        "django.middleware.locale.LocaleMiddleware"
    )


@PUBLIC_HEADERS
def test_dashboard_keeps_vary(client):
    response = client.get("/espace/connexion")
    assert "accept-language" in response.get("Vary", "").lower()


@PUBLIC_HEADERS
def test_error_pages_short_public_cache(client):
    response = client.get("/personne-inconnue")
    assert response.status_code == 404
    assert cc(response) == {"public", "max-age=60"}
    profile = indexable_profile()
    slug = profile.slug
    delete_profile(profile)
    response = client.get(f"/{slug}")
    assert response.status_code == 410
    assert cc(response) == {"public", "max-age=60"}
    assert "accept-language" not in response.get("Vary", "").lower()


@PUBLIC_HEADERS
def test_dashboard_404_is_not_publicly_cached(client):
    response = client.get("/espace/nexiste-pas")
    assert response.status_code == 404
    assert "public" not in response.get("Cache-Control", "")


def test_vcard_cache_control(client):
    profile = indexable_profile()
    response = client.get(f"/{profile.slug}/contact.vcf")
    assert cc(response) == {"public", "max-age=300"}
    private = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
    client.force_login(private.user)
    response = client.get(f"/{private.slug}/contact.vcf")
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]


def test_owner_private_page_stays_private(client):
    profile = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
    client.force_login(profile.user)
    response = client.get(f"/{profile.slug}")
    assert "public" not in response["Cache-Control"]


# --- 8. Open Graph defaults ------------------------------------------------------------------


def test_listing_pages_have_default_og_image(client, settings):
    fill_directory(settings)
    for path in ("/", "/villes/douala", "/plombiers/douala"):
        _, body = body_of(client, path)
        assert meta_content(body, "property", "og:image") == "https://profils.test/static/img/og-default.png"
        assert meta_content(body, "property", "og:image:width") == "1200"
        assert meta_content(body, "property", "og:image:height") == "630"
        assert meta_content(body, "name", "twitter:card") == "summary_large_image"
        assert meta_content(body, "property", "og:locale") == "fr_CM"


def test_static_brand_images():
    from pathlib import Path

    from django.conf import settings
    from PIL import Image

    with Image.open(Path(settings.BASE_DIR) / "static/img/og-default.png") as og:
        assert og.size == (1200, 630)
    with Image.open(Path(settings.BASE_DIR) / "static/img/logo.png") as logo:
        assert logo.size == (512, 512)


def test_profile_og_locale(client):
    profile = indexable_profile(language="en")
    _, body = body_of(client, f"/{profile.slug}")
    assert meta_content(body, "property", "og:locale") == "en_CM"
    profile = indexable_profile()
    _, body = body_of(client, f"/{profile.slug}")
    assert meta_content(body, "property", "og:locale") == "fr_CM"


# --- 10. rel of outbound links ---------------------------------------------------------------


def test_contact_links_are_nofollow(client):
    profile = indexable_profile(address="Rue 12")
    _, body = body_of(client, f"/{profile.slug}")
    for kind in ("whatsapp", "maps", "share"):
        assert re.search(rf'rel="nofollow noopener" data-track="{kind}"', body), kind
    assert body.count('rel="ugc nofollow noopener"') == 2  # the pro's own links


# --- 12. hide_branding savepoint -------------------------------------------------------------


def test_hide_branding_database_error_keeps_banner(client, monkeypatch):
    def broken(profile, entitlement):
        raise DatabaseError("relation missing")

    monkeypatch.setattr("apps.billing.services.has", broken)
    profile = indexable_profile()
    response, body = body_of(client, f"/{profile.slug}")
    assert response.status_code == 200
    assert 'class="growth-banner"' in body


def test_hide_branding_unexpected_error_is_not_swallowed(client, monkeypatch):
    def broken(profile, entitlement):
        raise RuntimeError("bug")

    monkeypatch.setattr("apps.billing.services.has", broken)
    profile = indexable_profile()
    client.raise_request_exception = False
    assert client.get(f"/{profile.slug}").status_code == 500


# --- 13. seo_audit --crawl -------------------------------------------------------------------


def test_seo_audit_crawl_clean_site(settings):
    fill_directory(settings)
    out = StringIO()
    call_command("seo_audit", "--crawl", stdout=out)
    text = out.getvalue()
    assert "0 erreur(s)" in text, text
    assert "aucune erreur" in text


def test_seo_audit_crawl_below_threshold_is_coherent():
    indexable_profile()
    out = StringIO()
    call_command("seo_audit", "--crawl", "--limit", "5", stdout=out)
    assert "0 erreur(s)" in out.getvalue()


def test_seo_audit_crawl_reports_errors(settings, monkeypatch):
    fill_directory(settings)
    monkeypatch.setattr("apps.seo.audit.TITLE_MAX", 10)
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("seo_audit", "--crawl", stdout=out)
    assert "title de" in out.getvalue()


def test_crawler_detects_broken_links_and_noindex_breadcrumb():
    from apps.seo.audit import Crawler, PageParser

    parser = PageParser()
    parser.feed(
        "<html><head><title>t</title></head><body><h1>a</h1><h1>b</h1>"
        '<nav class="breadcrumb"><ol><li><a href="/nexiste-pas">x</a></li></ol></nav>'
        '<a href="https://ailleurs.test/">ext</a><a href="tel:+237">tel</a></body></html>'
    )
    assert parser.h1 == 2
    assert parser.breadcrumb_links == ["/nexiste-pas"]
    crawler = Crawler()
    assert crawler.internal_path("https://ailleurs.test/", "/") is None
    assert crawler.internal_path("tel:+237", "/") is None
    assert crawler.internal_path("?page=2", "/plombiers/douala") == "/plombiers/douala?page=2"
    assert crawler.status("/nexiste-pas") == 404
    assert crawler.status("/nexiste-pas") == 404  # cached


def test_unresolved_refs():
    block = {"@graph": [{"@id": "#a", "x": {"@id": "#b"}}, {"@id": "#c", "y": [{"@id": "#a"}]}]}
    assert jsonld.unresolved_refs(block) == ["#b"]
