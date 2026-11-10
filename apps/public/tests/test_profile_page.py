"""Profile page: HTTP status for every case, SEO head, JSON-LD, content and resources."""

import html
import io
import re

import pytest
from django.utils import timezone
from PIL import Image

from apps.profiles.models import Profile, ProfileMedia
from apps.profiles.services import change_slug, delete_profile, refresh_seo_state, suspend_profile
from apps.seo.tests.utils import graph_node, indexable_profile, meta_content
from tests.factories import CardFactory, ProfileFactory

pytestmark = pytest.mark.django_db


def page(client, path, **kwargs):
    response = client.get(path, **kwargs)
    return response, response.content.decode()


# --- status codes ---------------------------------------------------------------------------


def test_public_profile_is_200(client):
    profile = indexable_profile()
    response, body = page(client, f"/{profile.slug}")
    assert response.status_code == 200
    assert body.count("<h1") == 1
    assert "public" in response["Cache-Control"]


def test_old_slug_redirects_301(client):
    profile = indexable_profile()
    old = profile.slug
    change_slug(profile, "nouvelle-adresse-test")
    response = client.get(f"/{old}")
    assert response.status_code == 301
    assert response["Location"] == "/nouvelle-adresse-test"


def test_trailing_slash_redirects_301(client):
    profile = indexable_profile()
    response = client.get(f"/{profile.slug}/")
    assert response.status_code == 301
    assert response["Location"] == f"/{profile.slug}"


def test_uppercase_slug_redirects_to_lowercase(client):
    profile = indexable_profile()
    response = client.get(f"/{profile.slug.upper()}")
    assert response.status_code == 301
    assert response["Location"] == f"/{profile.slug}"


def test_unknown_and_reserved_slugs_are_404(client):
    assert client.get("/personne-inconnue").status_code == 404
    assert client.get("/douala").status_code == 404  # reserved (city)
    assert client.get("/villes").status_code == 404  # reserved (system)


def test_private_profile_is_404_for_visitors(client):
    profile = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
    assert client.get(f"/{profile.slug}").status_code == 404
    for suffix in ("contact.vcf", "qr.svg", "qr.png", "og.png"):
        assert client.get(f"/{profile.slug}/{suffix}").status_code == 404


def test_private_profile_visible_to_owner_with_noindex(client):
    profile = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
    client.force_login(profile.user)
    response, body = page(client, f"/{profile.slug}")
    assert response.status_code == 200
    assert meta_content(body, "name", "robots") == "noindex, follow"
    assert response["X-Robots-Tag"] == "noindex"
    assert "Ta page est privée" in body
    assert "no-store" in response["Cache-Control"]


def test_other_user_cannot_see_private_profile(client):
    profile = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
    client.force_login(ProfileFactory().user)
    assert client.get(f"/{profile.slug}").status_code == 404


def test_suspended_profile_is_404_even_for_owner(client):
    profile = indexable_profile()
    suspend_profile(profile, "fraude")
    response = client.get(f"/{profile.slug}")
    assert response.status_code == 404
    assert profile.display_name.encode() not in response.content
    client.force_login(profile.user)
    assert client.get(f"/{profile.slug}").status_code == 404
    assert client.get(f"/{profile.slug}/contact.vcf").status_code == 404


def test_erased_profile_is_410(client):
    profile = indexable_profile()
    slug = profile.slug
    delete_profile(profile)
    response, body = page(client, f"/{slug}")
    assert response.status_code == 410
    assert "supprimée" in body
    assert meta_content(body, "name", "robots") == "noindex, follow"
    assert client.get(f"/{slug}/contact.vcf").status_code == 410


def test_old_slug_of_erased_profile_is_410(client):
    profile = indexable_profile()
    old = profile.slug
    change_slug(profile, "adresse-avant-effacement")
    delete_profile(Profile.objects.get(pk=profile.pk))
    assert client.get(f"/{old}").status_code == 410


def test_deleted_status_is_410(client):
    profile = ProfileFactory()
    Profile.objects.filter(pk=profile.pk).update(status=Profile.Status.DELETED)
    assert client.get(f"/{profile.slug}").status_code == 410


def test_post_not_allowed(client):
    profile = indexable_profile()
    assert client.post(f"/{profile.slug}").status_code == 405


# --- SEO head -------------------------------------------------------------------------------


def test_head_tags_of_indexable_profile(client):
    profile = indexable_profile(display_name="Paul Ndongo")
    _, body = page(client, f"/{profile.slug}")
    title = html.unescape(re.search(r"<title>(.*?)</title>", body).group(1))
    assert title == "Paul Ndongo – Plombier à Douala"
    assert len(title) <= 60
    description = html.unescape(meta_content(body, "name", "description"))
    assert 150 <= len(description) <= 160
    assert f'<link rel="canonical" href="https://profils.test/{profile.slug}">' in body
    assert meta_content(body, "name", "robots") == "index, follow"
    assert '<html lang="fr">' in body


def test_canonical_ignores_query_parameters(client):
    profile = indexable_profile()
    _, body = page(client, f"/{profile.slug}?utm_source=whatsapp&fbclid=x")
    assert f'<link rel="canonical" href="https://profils.test/{profile.slug}">' in body


def test_non_indexable_profile_is_noindex_follow(client):
    profile = ProfileFactory(bio="Trop court")
    refresh_seo_state(profile)
    response, body = page(client, f"/{profile.slug}")
    assert response.status_code == 200
    assert meta_content(body, "name", "robots") == "noindex, follow"


def test_english_profile_sets_html_lang(client):
    profile = indexable_profile(language="en")
    _, body = page(client, f"/{profile.slug}")
    assert '<html lang="en">' in body


def test_open_graph_and_twitter_tags(client):
    profile = indexable_profile()
    _, body = page(client, f"/{profile.slug}")
    assert meta_content(body, "property", "og:type") == "profile"
    assert meta_content(body, "property", "og:url") == f"https://profils.test/{profile.slug}"
    image = meta_content(body, "property", "og:image")
    assert image.startswith(f"https://profils.test/{profile.slug}/og.png")
    assert meta_content(body, "property", "og:image:width") == "1200"
    assert meta_content(body, "property", "og:image:height") == "630"
    assert meta_content(body, "name", "twitter:card") == "summary_large_image"


def test_jsonld_business_and_breadcrumb(client, settings):
    profile = indexable_profile(display_name="Paul Ndongo")
    for _ in range(settings.SEO_DIRECTORY_MIN_PROFILES - 1):
        indexable_profile()  # city and directory pages meet the threshold: breadcrumb levels are linked
    profile.services.update(price_label="dès 5 000 FCFA")
    _, body = page(client, f"/{profile.slug}")
    entity = graph_node(body, "Plumber")
    crumbs = graph_node(body, "BreadcrumbList")
    assert entity["@type"] == "Plumber"
    assert entity["name"] == "Paul Ndongo"
    assert entity["url"] == f"https://profils.test/{profile.slug}"
    assert entity["address"]["addressLocality"] == "Douala"
    assert entity["address"]["addressCountry"] == "CM"
    assert entity["telephone"] == profile.phone_public
    assert entity["sameAs"] == ["https://exemple.test/0", "https://exemple.test/1"]
    assert len(entity["makesOffer"]) == 2
    assert entity["makesOffer"][0]["description"] == "dès 5 000 FCFA"
    assert entity["areaServed"] == "Douala"
    assert crumbs["@type"] == "BreadcrumbList"
    names = [item["name"] for item in crumbs["itemListElement"]]
    assert names == ["Accueil", "Douala", "Plombiers à Douala", "Paul Ndongo"]
    assert crumbs["itemListElement"][2]["item"] == "https://profils.test/plombiers/douala"


def test_jsonld_escapes_script_injection(client):
    bio = "</script><script>alert(1)</script> & <b>gras</b> " + " ".join(f"mot{i}" for i in range(70))
    profile = indexable_profile(bio=bio)
    _, body = page(client, f"/{profile.slug}")
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S).group(1)
    assert "<" not in raw
    assert ">" not in raw
    assert "&" not in raw
    assert "<script>alert(1)" not in body  # the visible bio is escaped too
    entity = graph_node(body, "Plumber")
    assert "alert(1)" in entity["description"]


# --- content --------------------------------------------------------------------------------


def test_action_buttons_and_tracking(client):
    profile = indexable_profile(email_public="paul@exemple.test", address="Rue 12, Akwa")
    _, body = page(client, f"/{profile.slug}")
    digits = profile.whatsapp.lstrip("+")
    assert f'href="tel:{profile.phone_public}" data-track="call"' in body
    assert f'href="https://wa.me/{digits}"' in body
    assert 'href="mailto:paul@exemple.test" data-track="email"' in body
    assert "https://www.google.com/maps/search/?api=1&amp;query=Rue+12" in body
    assert f'href="/{profile.slug}/contact.vcf"' in body
    for kind in ("call", "whatsapp", "email", "maps", "vcard", "link", "share"):
        assert f'data-track="{kind}"' in body
    assert f'data-profile-id="{profile.pk}"' in body
    assert f'<img class="pixel" src="/p/{profile.pk}.gif" width="1" height="1" alt="" loading="eager">' in body
    assert "https://wa.me/?text=" in body
    assert f'href="/signaler/{profile.slug}"' in body
    assert "<script>" not in body  # strict CSP: no inline JS
    assert 'src="/static/js/profile.js" defer' in body


def test_user_links_are_ugc_nofollow_and_http_only(client):
    profile = indexable_profile()
    profile.links.create(kind="other", url="javascript:alert(1)")
    _, body = page(client, f"/{profile.slug}")
    assert "javascript:" not in body
    assert body.count('rel="ugc nofollow noopener"') == 2


def test_bio_is_escaped_with_linebreaks(client):
    profile = indexable_profile(bio="Ligne <b>un</b>\nLigne deux " + " ".join(f"m{i}" for i in range(70)))
    _, body = page(client, f"/{profile.slug}")
    assert "&lt;b&gt;un&lt;/b&gt;<br>Ligne deux" in body


def test_gallery_alt_and_lazy_loading(client):
    profile = indexable_profile(display_name="Paul Ndongo")
    for i in range(2):
        ProfileMedia.objects.create(
            profile=profile, image=f"profiles/{profile.pk}/gallery/{i}.webp", width=800, height=600, order=i
        )
    _, body = page(client, f"/{profile.slug}")
    imgs = re.findall(r'<img src="/media/profiles/[^"]+gallery[^>]+>', body)
    assert len(imgs) == 2
    assert 'alt="Réalisation de Paul Ndongo, plombier à Douala"' in imgs[0]
    assert "loading=" not in imgs[0]
    assert 'loading="lazy"' in imgs[1]
    assert 'width="800" height="600"' in imgs[1]


def test_verified_badge(client):
    profile = indexable_profile(verified_at=timezone.now())
    _, body = page(client, f"/{profile.slug}")
    assert "Profil vérifié" in body


def test_similar_profiles_block(client):
    profile = indexable_profile()
    others = [indexable_profile() for _ in range(3)]
    _, body = page(client, f"/{profile.slug}")
    assert "Autres plombiers à Douala" in body
    for other in others:
        assert f'href="/{other.slug}"' in body


def test_growth_banner_shown_on_free_plan(client):
    profile = indexable_profile()
    _, body = page(client, f"/{profile.slug}")
    assert 'class="growth-banner"' in body


def test_growth_banner_hidden_with_hide_branding(client, monkeypatch):
    monkeypatch.setattr("apps.billing.services.has", lambda profile, ent: ent == "hide_branding")
    profile = indexable_profile()
    _, body = page(client, f"/{profile.slug}")
    assert 'class="growth-banner"' not in body


# --- resources ------------------------------------------------------------------------------


def test_vcard(client):
    profile = indexable_profile(display_name="Paul; Ndongo, fils", email_public="paul@exemple.test")
    response = client.get(f"/{profile.slug}/contact.vcf")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/vcard")
    assert response["X-Robots-Tag"] == "noindex"
    assert f'filename="{profile.slug}.vcf"' in response["Content-Disposition"]
    text = response.content.decode()
    assert text.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n")
    assert text.endswith("END:VCARD\r\n")
    assert "\n" not in text.replace("\r\n", "")
    assert "FN:Paul\\; Ndongo\\, fils\r\n" in text
    assert f"TEL;TYPE=CELL,VOICE:{profile.phone_public}\r\n" in text
    assert "EMAIL;TYPE=INTERNET:paul@exemple.test\r\n" in text
    assert f"URL:https://profils.test/{profile.slug}\r\n" in text
    assert "PHOTO" not in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_vcard_old_slug_redirects(client):
    profile = indexable_profile()
    old = profile.slug
    change_slug(profile, "adresse-vcard-test")
    response = client.get(f"/{old}/contact.vcf")
    assert response.status_code == 301
    assert response["Location"] == "/adresse-vcard-test/contact.vcf"


def test_qr_svg_and_png(client):
    profile = indexable_profile()
    svg = client.get(f"/{profile.slug}/qr.svg")
    assert svg.status_code == 200
    assert svg["Content-Type"] == "image/svg+xml"
    assert svg["X-Robots-Tag"] == "noindex"
    assert b"<svg" in svg.content
    assert f'filename="qr-{profile.slug}.svg"' in svg["Content-Disposition"]
    png = client.get(f"/{profile.slug}/qr.png?download=1")
    assert png.status_code == 200
    assert png["Content-Type"] == "image/png"
    assert png["Content-Disposition"].startswith("attachment;")
    assert Image.open(io.BytesIO(png.content)).format == "PNG"


def test_qr_target_prefers_active_card():
    from apps.public.views import qr_target

    profile = indexable_profile()
    assert qr_target(profile) == f"https://profils.test/{profile.slug}"
    CardFactory(public_code="K7M2QXP", status="active", profile=profile, activated_at=timezone.now())
    assert qr_target(profile) == "https://profils.test/c/K7M2QXP"


def test_og_image(client):
    profile = indexable_profile(display_name="Marie-Claire Ebogo Atangana Mballa Nkoulou")
    response = client.get(f"/{profile.slug}/og.png")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["X-Robots-Tag"] == "noindex"
    assert len(response.content) < 300 * 1024
    image = Image.open(io.BytesIO(response.content))
    assert image.size == (1200, 630)
    again = client.get(f"/{profile.slug}/og.png")  # served from the storage cache
    assert again.content == response.content
