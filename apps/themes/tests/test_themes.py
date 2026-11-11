"""Site templates: catalogue, rendering invariants, theme.css, dashboard flows, publication, toggles."""

import json
import re
from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Plan
from apps.billing.services import grant_plan
from apps.platform.models import SiteSettings
from apps.platform.services import invalidate
from apps.profiles.models import Profile
from apps.seo.models import IndexingQueue
from apps.seo.tests.utils import indexable_profile, jsonld_blocks, meta_content
from apps.themes import services
from apps.themes.models import ProfileTheme, Theme
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/ld\+json)[^>]*>", re.I)


def switch(**flags):
    obj, _ = SiteSettings.objects.get_or_create(pk=1)
    for name, value in flags.items():
        setattr(obj, name, value)
    obj.save()
    invalidate()


def apply_theme(profile, code, **data):
    theme = Theme.objects.get(code=code)
    defaults = services.theme_defaults(theme)
    defaults.update(data)
    return ProfileTheme.objects.update_or_create(
        profile=profile,
        defaults={
            "theme": theme,
            "palette": defaults["palette"],
            "font_pair": defaults["font_pair"],
            "corners": defaults["corners"],
            "hero_variant": defaults["hero_variant"],
            "cta_label": defaults["cta_label"],
            "sections": defaults["sections"],
            "published_version": 1,
            "published_at": timezone.now(),
        },
    )[0]


def body_of(response) -> str:
    return response.content.decode()


def seo_invariants(html: str) -> dict:
    blocks = jsonld_blocks(html)
    return {
        "title": re.search(r"<title>(.*?)</title>", html, re.S).group(1),
        "canonical": re.search(r'<link rel="canonical" href="([^"]+)">', html).group(1),
        "robots": meta_content(html, "name", "robots"),
        "description": meta_content(html, "name", "description"),
        "og_title": meta_content(html, "property", "og:title"),
        "h1": html.count("<h1"),
        "jsonld": blocks,
    }


def premium_profile(profile):
    grant_plan(profile, Plan.objects.get(code="essentiel"))
    return profile


# --- catalogue ------------------------------------------------------------------------------


def test_seed_creates_professional_catalogue():
    themes = list(Theme.objects.all())
    assert len(themes) >= 12
    assert {t.category for t in themes} == set(Theme.Category.values)
    assert sum(1 for t in themes if not t.is_premium) >= 6
    signature = Theme.objects.get(code=services.DEFAULT_THEME_CODE)
    assert signature.font_pair == "archivo" and not signature.is_premium
    assert signature.palette["primary"] == "#0A7F7D"
    assert not {t.code for t in themes} & services.RESERVED_CODES
    for t in themes:
        assert services.clean_palette(t.palette) == {k: v.upper() for k, v in t.palette.items() if k != "name"}
        assert t.layout in services.LAYOUTS and t.font_pair in services.FONT_PAIRS and t.corners in services.CORNERS
        assert len(t.palette_presets) >= 3


def test_paid_plans_unlock_premium_themes():
    plans = {p.code: p.entitlements for p in Plan.objects.all()}
    for code in ("essentiel", "pro", "team"):
        assert plans[code]["premium_themes"] is True
    assert not plans["free"].get("premium_themes")


# --- colours ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "palette",
    [
        {"primary": "#FFFF00", "accent": "#FFFFFF", "background": "#FFFFFF", "surface": "#FAFAFA", "text": "#EEEEEE"},
        {"primary": "#777777", "accent": "#000000", "background": "#000000", "surface": "#111111", "text": "#222222"},
        {"primary": "#17BDBB", "accent": "#FD6552", "background": "#EEF4F3", "surface": "#FFFFFF", "text": "#16242C"},
    ],
)
def test_tokens_are_aa_whatever_the_user_picks(palette):
    t = services.derive_tokens(palette)
    for bg in (t["bg"], t["surface"]):
        assert services.contrast(t["text"], bg) >= 4.5
        assert services.contrast(t["muted"], bg) >= 4.5
        assert services.contrast(t["primary-ink"], bg) >= 4.5
    assert services.contrast(t["on-primary"], t["primary"]) >= 4.5
    assert services.contrast(t["on-accent"], t["accent"]) >= 4.5


def test_invalid_colours_never_reach_the_stylesheet():
    palette = services.clean_palette({"primary": "red;}body{x:y", "text": "#12345G"})
    assert palette["primary"] == "#0A7F7D" and palette["text"] == "#16242C"


# --- public rendering -------------------------------------------------------------------------


def test_profile_without_theme_uses_signature(client):
    profile = indexable_profile()
    html = body_of(client.get(f"/{profile.slug}"))
    assert "t--cover_color" in html
    assert "/static/css/themes/base.css" in html
    assert f"/{profile.slug}/theme.css?v=" in html
    assert "/static/css/fonts.css" in html  # Archivo (self-hosted)


@pytest.mark.parametrize("code", list(services.LAYOUTS))
def test_every_layout_keeps_seo_invariants(client, code):
    profile = indexable_profile(
        email_public="paul@exemple.test", address="Rue 12", opening_hours={"mo": [["08:00", "18:00"]]}
    )
    reference = seo_invariants(body_of(client.get(f"/{profile.slug}")))
    apply_theme(profile, "signature", hero_variant=code)
    response = client.get(f"/{profile.slug}")
    html = body_of(response)
    assert response.status_code == 200
    assert seo_invariants(html) == reference
    assert f"t--{code}" in html
    assert 'style="' not in html and " style=" not in html
    assert not INLINE_SCRIPT_RE.search(html)
    assert reference["h1"] == 1


def test_every_seeded_theme_renders_a_complete_page(client):
    profile = indexable_profile(
        email_public="paul@exemple.test", address="Rue 12", opening_hours={"mo": [["08:00", "18:00"]]}
    )
    reference = seo_invariants(body_of(client.get(f"/{profile.slug}")))
    assert reference["robots"].startswith("index")
    for theme in Theme.objects.all():
        apply_theme(profile, theme.code)
        html = body_of(client.get(f"/{profile.slug}"))
        assert seo_invariants(html) == reference, theme.code
        assert f"t--{theme.layout}" in html
        assert "Réparation de fuites" in html  # services section
        assert "Lundi" in html  # hours section
        assert 'id="contact"' in html
        assert not INLINE_SCRIPT_RE.search(html)
        assert " style=" not in html
        assert len(html.encode()) < 60_000  # HTML budget (page < 150 KB with CSS, photos excluded)


def test_sections_order_and_visibility(client):
    profile = indexable_profile()
    apply_theme(
        profile,
        "signature",
        sections=[
            {"key": "links", "visible": True},
            {"key": "about", "visible": False},
            {"key": "contact", "visible": False},
        ],
    )
    html = body_of(client.get(f"/{profile.slug}"))
    assert html.index('id="liens"') < html.index('id="presentation"')  # order respected
    assert 'id="presentation"' in html  # the bio can never be hidden (SEO)
    assert 'id="contact"' not in html


def test_theme_css_is_versioned_and_cached(client):
    profile = indexable_profile()
    apply_theme(profile, "code")
    html = body_of(client.get(f"/{profile.slug}"))
    version = re.search(rf"/{profile.slug}/theme.css\?v=([0-9a-f]+)", html).group(1)
    response = client.get(f"/{profile.slug}/theme.css?v={version}")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/css")
    assert response["X-Robots-Tag"] == "noindex"
    assert "immutable" in response["Cache-Control"] and "max-age=31536000" in response["Cache-Control"]
    css = body_of(response)
    assert "--c-primary:#6D5DF6" in css and "color-scheme:dark" in css
    stale = client.get(f"/{profile.slug}/theme.css?v=old")
    assert "max-age=300" in stale["Cache-Control"] and "immutable" not in stale["Cache-Control"]


def test_theme_css_follows_profile_visibility(client):
    profile = indexable_profile()
    Profile.objects.filter(pk=profile.pk).update(visibility=Profile.Visibility.PRIVATE)
    assert client.get(f"/{profile.slug}/theme.css").status_code == 404
    client.force_login(profile.user)
    response = client.get(f"/{profile.slug}/theme.css")
    assert response.status_code == 200 and "no-store" in response["Cache-Control"]


# --- dashboard --------------------------------------------------------------------------------


@pytest.fixture
def pro(client):
    profile = indexable_profile()
    client.force_login(profile.user)
    return profile


def test_gallery_requires_login(client):
    response = client.get(reverse("themes:gallery"))
    assert response.status_code == 302


def test_gallery_lists_themes_with_badges(client, pro):
    response = client.get(reverse("themes:gallery"))
    html = body_of(response)
    assert response.status_code == 200
    assert "Modulis Signature" in html and "Actuel" in html
    assert "Premium" in html and "Gratuit" in html and "Débloquer" in html
    assert "/static/img/themes/chantier.svg" in html
    filtered = body_of(client.get(reverse("themes:gallery") + "?categorie=artisan_btp"))
    assert "Chantier" in filtered and "Éclat" not in filtered


def test_free_plan_cannot_use_premium_theme(client, pro):
    response = client.post(reverse("themes:use", args=["saveur"]))
    assert response.status_code == 302 and response["Location"] == reverse("themes:gallery")
    assert not ProfileTheme.objects.filter(profile=pro, draft__theme="saveur").exists()


def test_paid_plan_can_use_premium_theme(client, pro):
    premium_profile(pro)
    response = client.post(reverse("themes:use", args=["saveur"]))
    assert response["Location"] == reverse("themes:customize")
    assert ProfileTheme.objects.get(profile=pro).draft["theme"] == "saveur"


def test_preview_is_private_noindex_and_frameable_by_us_only(client, pro):
    other = indexable_profile(display_name="Quelqu'un D'autre")
    response = client.get(reverse("themes:preview", args=["chantier"]))
    html = body_of(response)
    assert response.status_code == 200
    assert pro.display_name in html and other.display_name not in html  # own page only (no IDOR)
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in response["Content-Security-Policy"]
    assert "no-store" in response["Cache-Control"] and "noindex" in response["X-Robots-Tag"]
    assert meta_content(html, "name", "robots").startswith("noindex")
    assert "t--split_photo" in html
    assert "data-profile-id" not in html and "/p/" not in html  # previews never count as visits
    css = client.get(reverse("themes:preview_css", args=["chantier"]))
    assert "--c-primary:#1F3A5F" in body_of(css) and "no-store" in css["Cache-Control"]
    # The live page is untouched and still not frameable.
    live = client.get(f"/{pro.slug}")
    assert "t--cover_color" in body_of(live)
    assert "frame-ancestors 'none'" in live["Content-Security-Policy"]


def test_detail_page_embeds_preview(client, pro):
    response = client.get(reverse("themes:detail", args=["eclat"]))
    assert response.status_code == 200
    assert reverse("themes:preview", args=["eclat"]) in body_of(response)
    frame_src = re.search(r"frame-src ([^;]*)", response["Content-Security-Policy"]).group(1)
    assert "'self'" in frame_src.split()
    assert client.get(reverse("themes:detail", args=["inconnu"])).status_code == 404


def test_customizer_saves_draft_without_touching_live_page(client, pro):
    client.post(reverse("themes:use", args=["chantier"]))
    data = {
        "preset": "custom",
        "color_primary": "#123456",
        "color_accent": "#ff8800",
        "color_background": "#ffffff",
        "color_surface": "#ffffff",
        "color_text": "#111111",
        "font_pair": "serif",
        "corners": "soft",
        "hero_variant": "editorial",
        "cta_label": "  Demander   un devis ",
        "order": ["gallery", "services", "about", "hours", "area", "links", "contact"],
        "visible_gallery": "on",
        "visible_services": "on",
        "visible_hours": "on",
        "move": "about:up",
    }
    response = client.post(reverse("themes:customize"), data, HTTP_X_REQUESTED_WITH="theme-editor")
    assert response.status_code == 200 and response.json()["ok"]
    draft = ProfileTheme.objects.get(profile=pro).draft
    assert draft["palette"]["primary"] == "#123456"
    assert draft["cta_label"] == "Demander un devis"
    assert [s["key"] for s in draft["sections"]][:3] == ["gallery", "about", "services"]
    visible = {s["key"]: s["visible"] for s in draft["sections"]}
    assert visible["about"] and visible["services"] and not visible["contact"]
    preview = body_of(client.get(response.json()["preview_url"]))
    assert "t--editorial" in preview and "Demander un devis" in preview
    assert "t--cover_color" in body_of(client.get(f"/{pro.slug}"))  # not published yet


def test_customizer_rejects_invalid_values(client, pro):
    client.post(reverse("themes:use", args=["chantier"]))
    data = {
        "preset": "custom",
        "color_primary": "javascript:x",
        "font_pair": "comic",
        "corners": "soft",
        "hero_variant": "card",
    }
    response = client.post(reverse("themes:customize"), data, HTTP_X_REQUESTED_WITH="theme-editor")
    assert response.status_code == 400 and not response.json()["ok"]
    page = client.post(reverse("themes:customize"), data)
    assert page.status_code == 400 and "couleurs valides" in body_of(page)


def test_customizer_without_js_moves_sections(client, pro):
    client.post(reverse("themes:use", args=["signature"]))
    page = body_of(client.get(reverse("themes:customize")))
    assert "frame-src" not in page  # sanity: CSP lives in headers only
    data = {
        "preset": "0",
        "font_pair": "archivo",
        "corners": "rounded",
        "hero_variant": "cover_color",
        "order": list(services.SECTION_KEYS),
        "move": "contact:up",
        "visible_contact": "on",
    }
    response = client.post(reverse("themes:customize"), data)
    assert response.status_code == 302
    keys = [s["key"] for s in ProfileTheme.objects.get(profile=pro).draft["sections"]]
    assert keys.index("contact") < keys.index("links")


def test_publish_goes_live_and_notifies_immediately(client, pro, django_capture_on_commit_callbacks, settings):
    settings.KLIZ_ENABLED = True
    client.post(reverse("themes:use", args=["horizon"]))
    before = Profile.objects.get(pk=pro.pk).content_updated_at
    old_css = re.search(r"theme\.css\?v=(\w+)", body_of(client.get(f"/{pro.slug}"))).group(1)
    readiness = client.get(reverse("themes:publish"))
    assert "Prête pour Google" in body_of(readiness)
    with mock.patch("apps.seo.tasks.flush_now") as flush, django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("themes:publish"))
    assert response["Location"] == reverse("themes:published")
    flush.assert_called_once()
    pt = ProfileTheme.objects.get(profile=pro)
    assert pt.theme.code == "horizon" and pt.published_version == 1 and pt.draft == {}
    assert Profile.objects.get(pk=pro.pk).content_updated_at > before
    queued = set(IndexingQueue.objects.values_list("url", flat=True))
    assert pro.absolute_url in queued and "https://profils.test/villes/douala" in queued
    live = body_of(client.get(f"/{pro.slug}"))
    assert "t--split_photo" in live
    assert re.search(r"theme\.css\?v=(\w+)", live).group(1) != old_css
    done = client.get(reverse("themes:published"))
    html = body_of(done)
    assert "Ta page est en ligne — Google et Bing sont prévenus" in html
    assert pro.absolute_url in html and "https://wa.me/?text=" in html
    status = client.get(reverse("themes:published_status"))
    assert status.status_code == 200 and "tm-status--queued" in body_of(status)  # flush_now mocked
    assert 'hx-trigger="every 3s"' in body_of(status)  # polled until the notification is final
    from apps.seo.models import IndexingLog

    IndexingLog.objects.create(provider="IndexNowProvider", success=True, urls=[pro.absolute_url], status_code=200)
    IndexingQueue.objects.all().delete()
    final = body_of(client.get(reverse("themes:published_status")))
    assert "tm-status--sent" in final and "hx-trigger" not in final
    settings.KLIZ_ENABLED = False  # notifications off: the success screen must not claim Google was told
    html = body_of(client.get(reverse("themes:published")))
    assert "Google et Bing sont prévenus" not in html and "tm-status--disabled" in html


def test_flush_now_runs_the_notifier_path():
    from apps.seo import tasks

    with mock.patch("apps.seo.notifier.flush_queue", return_value=3) as flush:
        tasks.flush_now()
    flush.assert_called_once()
    switch(indexing_notifications_enabled=False)
    with mock.patch("apps.seo.notifier.flush_queue") as flush:
        tasks.flush_now()
        tasks.flush_indexing_queue.call_local()
    flush.assert_not_called()


def test_publish_without_instant_feature_waits_for_batch(client, pro, django_capture_on_commit_callbacks):
    switch(instant_publish_enabled=False)
    client.post(reverse("themes:use", args=["chantier"]))
    with mock.patch("apps.seo.tasks.flush_now") as flush, django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("themes:publish"))
    flush.assert_not_called()
    assert IndexingQueue.objects.filter(url=pro.absolute_url).exists()


def test_publish_non_indexable_page_does_not_claim_google(client, django_capture_on_commit_callbacks):
    thin = ProfileFactory()
    client.force_login(thin.user)
    client.post(reverse("themes:use", args=["chantier"]))
    with mock.patch("apps.seo.tasks.flush_now") as flush, django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("themes:publish"))
    flush.assert_not_called()
    html = body_of(client.get(reverse("themes:published")))
    assert "Google et Bing sont prévenus" not in html and "Ta page est en ligne" in html


def test_premium_draft_cannot_be_published_after_downgrade(client, pro):
    premium_profile(pro)
    client.post(reverse("themes:use", args=["prestige"]))
    pro.subscriptions.update(
        ends_at=timezone.now() - timedelta(seconds=1), starts_at=timezone.now() - timedelta(days=2)
    )
    response = client.post(reverse("themes:publish"))
    assert response["Location"] == reverse("themes:publish")
    assert ProfileTheme.objects.get(profile=pro).published_version == 0


def test_themes_feature_off(client, pro):
    apply_theme(pro, "chantier")
    switch(themes_enabled=False)
    gallery = body_of(client.get(reverse("themes:gallery")))
    assert "momentanément indisponible" in gallery and "Utiliser ce modèle" not in gallery
    assert client.post(reverse("themes:use", args=["eclat"]))["Location"] == reverse("themes:gallery")
    assert client.post(reverse("themes:publish"))["Location"] == reverse("themes:gallery")
    assert "t--split_photo" in body_of(client.get(f"/{pro.slug}"))  # existing pages keep their theme


def test_suspended_profile_cannot_change_theme(client, pro):
    Profile.objects.filter(pk=pro.pk).update(status=Profile.Status.SUSPENDED)
    assert client.post(reverse("themes:use", args=["eclat"])).status_code == 403


# --- directory switch -------------------------------------------------------------------------


def test_directory_switch_off_hides_listings(client, settings):
    profiles = [indexable_profile() for _ in range(settings.SEO_DIRECTORY_MIN_PROFILES)]
    assert client.get("/villes/douala").status_code == 200
    switch(directory_enabled=False)
    assert client.get("/villes/douala").status_code == 404
    assert client.get("/plombiers/douala").status_code == 404
    from django.core.cache import cache

    cache.clear()
    assert "sitemap-annuaire.xml" not in body_of(client.get("/sitemap.xml"))
    html = body_of(client.get(f"/{profiles[0].slug}"))
    assert 'href="/villes/douala"' not in html and 'href="/plombiers/douala"' not in html
    graph = json.dumps(jsonld_blocks(html))
    assert "/villes/douala" not in graph
    assert 'href="/villes/douala"' not in body_of(client.get("/"))
