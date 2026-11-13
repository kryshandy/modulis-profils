"""Page builder (ADR-0012): content rules, placement, public rendering, SEO, security, moderation."""

import json
import re

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import escape

from apps.blocks import services
from apps.blocks.models import BlockImage, PageBlock
from apps.blocks.registry import BLOCK_TYPES, MAX_BLOCKS
from apps.dashboard.tests.helpers import make_image
from apps.seo.tests.utils import indexable_profile
from apps.themes import services as themes
from apps.themes.models import Theme
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def block(profile, kind, post=None, files=None):
    b = services.add_block(profile, kind)
    if post is not None:
        errors = services.update_block(b, post, files or {})
        assert not errors, errors
        b.refresh_from_db()
    return b


def page(client, profile):
    response = client.get(f"/{profile.slug}")
    return response, response.content.decode()


def outline_keys(profile):
    return [s["key"] for s in themes.page_outline(profile)]


# --- content rules ----------------------------------------------------------------------------


def test_text_is_plain_escaped_and_capped(client):
    profile = indexable_profile()
    block(profile, "text", {"f_title": "<b>Nos</b> garanties", "f_body": "<script>alert(1)</script>\nLigne 2"})
    _, html = page(client, profile)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;Nos&lt;/b&gt; garanties" in html
    b = services.add_block(profile, "text")
    errors = services.update_block(b, {"f_body": "x" * 3001}, {})
    assert "f_body" in errors


def test_control_characters_are_removed():
    assert services.clean_line("A‮B\x00C  D") == "ABC D"
    assert services.clean_paragraphs("a\r\n\r\n\r\n\r\nb") == "a\n\nb"


@pytest.mark.parametrize(
    "url", ["http://exemple.cm", "javascript:alert(1)", "https://", "ftp://x.cm/a", "https://a b.cm"]
)
def test_button_links_are_https_only(url):
    with pytest.raises(ValidationError):
        services.clean_https_url(url)


@pytest.mark.parametrize(
    ("url", "provider", "video_id"),
    [
        ("https://youtu.be/dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3", "youtube", "dQw4w9WgXcQ"),
        ("https://youtube.com/shorts/dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
        ("https://vimeo.com/123456789", "vimeo", "123456789"),
    ],
)
def test_video_links_are_recognised(url, provider, video_id):
    assert services.parse_video(url) == {"url": url, "provider": provider, "video_id": video_id}


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.cm/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/<script>",
        "https://vimeo.com/abc",
        "https://youtube.com/",
    ],
)
def test_unknown_video_links_are_refused(url):
    with pytest.raises(ValidationError):
        services.parse_video(url)


def test_required_fields_and_empty_rows():
    profile = ProfileFactory()
    b = services.add_block(profile, "faq")
    errors = services.update_block(b, {"i0_q": "Délai ?", "i0_a": "", "i1_q": "", "i1_a": ""}, {})
    assert list(errors) == ["i0_a"]
    errors = services.update_block(b, {"i0_q": "Délai ?", "i0_a": "48 h"}, {})
    assert not errors
    b.refresh_from_db()
    assert len(b.data["items"]) == 1  # empty rows dropped


def test_banner_link_requires_url():
    profile = ProfileFactory()
    b = services.add_block(profile, "banner")
    errors = services.update_block(b, {"f_title": "Devis gratuit", "f_button_action": "link"}, {})
    assert "f_button_url" in errors


def test_style_only_accepts_whitelisted_values():
    profile = ProfileFactory()
    b = block(profile, "text", {"f_body": "x", "s_background": "url(evil)", "s_spacing": "airy", "s_align": "center"})
    assert b.style == {"background": "auto", "spacing": "airy", "align": "center"}


def test_unknown_kind_and_block_limit():
    profile = ProfileFactory()
    with pytest.raises(ValidationError):
        services.add_block(profile, "html")
    for _ in range(MAX_BLOCKS):
        services.add_block(profile, "text")
    with pytest.raises(ValidationError):
        services.add_block(profile, "text")


# --- images -----------------------------------------------------------------------------------


def test_block_image_goes_through_the_photo_pipeline(client):
    profile = indexable_profile()
    b = block(profile, "text_image", {"f_body": "Atelier", "f_side": "left"}, {"img_image": make_image()})
    img = BlockImage.objects.get(block=b, slot="image")
    assert img.image.name.endswith(".webp") and img.width == 1200
    _, html = page(client, profile)
    assert img.image.url in html and "t-ti--left" in html


def test_a_non_image_file_is_refused():
    from django.core.files.uploadedfile import SimpleUploadedFile

    profile = ProfileFactory()
    b = services.add_block(profile, "text_image")
    fake = SimpleUploadedFile("x.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")
    errors = services.update_block(b, {"f_body": "x"}, {"img_image": fake})
    assert "img_image" in errors
    assert not BlockImage.objects.exists()


def test_before_after_needs_both_photos(client):
    profile = indexable_profile()
    b = block(
        profile,
        "before_after",
        {"f_title": "Rénovation", "i0_caption": "Salon"},
        {"img_before_0": make_image(), "img_after_0": make_image()},
    )
    _, html = page(client, profile)
    assert "t-ba__pair" in html
    services.update_block(b, {"f_title": "Rénovation", "i0_caption": "Salon", "del_after_0": "1"}, {})
    _, html = page(client, profile)
    assert "t-ba__pair" not in html


# --- placement --------------------------------------------------------------------------------


def test_new_block_goes_before_contact_and_contact_stays_last():
    profile = ProfileFactory()
    b = services.add_block(profile, "text")
    keys = outline_keys(profile)
    assert keys[-2:] == [b.key, "contact"]
    themes.move_section(profile, b.key, "down")
    assert outline_keys(profile)[-1] == "contact"
    themes.move_section(profile, "contact", "up")
    assert outline_keys(profile)[-1] == "contact"
    themes.move_section(profile, b.key, "up")
    assert outline_keys(profile).index(b.key) == len(keys) - 3


def test_outline_changes_are_mirrored_into_the_customizer_draft():
    profile = ProfileFactory()
    theme = Theme.objects.filter(is_premium=False, is_active=True).exclude(code=themes.DEFAULT_THEME_CODE).first()
    themes.start_with_theme(profile, theme)
    b = services.add_block(profile, "text")
    themes.move_section(profile, b.key, "up")
    pt = themes.settings_for(profile)
    assert [s["key"] for s in pt.sections] == [s["key"] for s in pt.draft["sections"]]
    themes.publish(profile)
    assert b.key in [s["key"] for s in themes.settings_for(profile).sections]


def test_locked_sections_cannot_be_hidden():
    profile = ProfileFactory()
    themes.set_section_visible(profile, "about", False)
    assert next(s for s in themes.page_outline(profile) if s["key"] == "about")["visible"] is True


def test_another_page_block_key_is_never_rendered(client):
    mine, other = indexable_profile(), indexable_profile()
    foreign = block(other, "text", {"f_title": "Secret", "f_body": "Texte d'une autre page"})
    themes.assign_theme(mine, Theme.objects.filter(layout="cover_color").first())
    pt = themes.settings_for(mine)
    pt.sections = [*pt.sections, {"key": foreign.key, "visible": True}]
    pt.save()
    _, html = page(client, mine)
    assert "Texte d&#x27;une autre page" not in html and "Texte d'une autre page" not in html


def test_deleting_a_block_removes_its_section_and_files():
    profile = ProfileFactory()
    b = block(profile, "text_image", {"f_body": "x"}, {"img_image": make_image()})
    services.delete_block(b)
    assert b.key not in outline_keys(profile)
    assert not BlockImage.objects.exists()


# --- public page and SEO ----------------------------------------------------------------------


def test_one_h1_and_one_h2_per_block(client):
    profile = indexable_profile()
    block(profile, "text", {"f_title": "Notre méthode", "f_body": "Visite gratuite."})
    block(profile, "steps", {"f_title": "Comment ça marche", "i0_title": "Appel", "i1_title": "Devis"})
    _, html = page(client, profile)
    assert html.count("<h1") == 1
    assert '<h2 class="t-h2" id="t-h-bloc-' in html
    assert html.count('<h3 class="t-step__title">') == 2
    assert "css/themes/blocks.css" in html


def test_empty_block_is_not_rendered_and_no_block_css_without_blocks(client):
    profile = indexable_profile()
    _, html = page(client, profile)
    assert "blocks.css" not in html
    services.add_block(profile, "text")  # still empty
    _, html = page(client, profile)
    assert "t-block" not in html and "blocks.css" not in html


def test_hidden_block_is_not_rendered(client):
    profile = indexable_profile()
    b = block(profile, "text", {"f_title": "Caché", "f_body": "Texte caché"})
    themes.set_section_visible(profile, b.key, False)
    _, html = page(client, profile)
    assert "Texte caché" not in html


def test_faq_adds_faqpage_structured_data(client):
    profile = indexable_profile()
    block(profile, "faq", {"f_title": "Questions", "i0_q": "Vous venez à domicile ?", "i0_a": "Oui, partout à Douala."})
    _, html = page(client, profile)
    graph = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))
    faq = next(n for n in graph["@graph"] if n["@type"] == "FAQPage")
    assert faq["mainEntity"][0]["name"] == "Vous venez à domicile ?"
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"] == "Oui, partout à Douala."


def test_testimonials_never_produce_review_markup(client):
    profile = indexable_profile()
    block(profile, "testimonials", {"i0_quote": "Travail propre", "i0_author": "Awa N."})
    _, html = page(client, profile)
    assert "Travail propre" in html
    assert '"Review"' not in html and "AggregateRating" not in html


def test_video_is_a_click_to_load_facade_with_scoped_csp(client):
    profile = indexable_profile()
    response, html = page(client, profile)
    assert "youtube" not in response.get("Content-Security-Policy", "")
    block(profile, "video", {"f_title": "Visite", "f_url": "https://youtu.be/dQw4w9WgXcQ"})
    response, html = page(client, profile)
    assert "<iframe" not in html
    assert 'data-embed="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?autoplay=1&amp;rel=0"' in html
    assert "js/blocks.js" in html
    csp = response["Content-Security-Policy"]
    assert "frame-src" in csp and "https://www.youtube-nocookie.com" in csp


def test_banner_buttons_use_the_page_contacts(client):
    profile = indexable_profile(whatsapp="+237690000123")
    block(
        profile,
        "banner",
        {"f_title": "Devis gratuit", "f_button_action": "whatsapp", "f_button_label": "Je veux un devis"},
    )
    block(profile, "banner", {"f_title": "Site", "f_button_action": "link", "f_button_url": "https://exemple.cm/x"})
    _, html = page(client, profile)
    assert 'href="https://wa.me/237690000123"' in html and "Je veux un devis" in html
    link = re.search(r'<a class="btn btn--primary t-banner__btn" href="https://exemple.cm/x"[^>]*>', html).group(0)
    assert 'rel="ugc nofollow noopener"' in link


def test_every_layout_renders_blocks(client):
    profile = indexable_profile()
    block(profile, "figures", {"f_title": "En chiffres", "i0_value": "12 ans", "i0_label": "d'expérience"})
    for layout in themes.LAYOUTS:
        themes.assign_theme(profile, Theme.objects.filter(layout=layout).first())
        response, html = page(client, profile)
        assert response.status_code == 200
        assert "12 ans" in html, layout


def test_page_weight_stays_within_budget_with_blocks(client):
    profile = indexable_profile()
    for kind in ("text", "faq", "steps", "figures", "testimonials"):
        post = {"f_title": "Titre", "f_body": "Texte " * 200}
        post.update(
            {
                "i0_q": "Q",
                "i0_a": "R",
                "i0_title": "É",
                "i0_value": "1",
                "i0_label": "L",
                "i0_quote": "Q",
                "i0_author": "A",
            }
        )
        block(profile, kind, post)
    response, _html = page(client, profile)
    assert len(response.content) < 120 * 1024


# --- pro space --------------------------------------------------------------------------------


def test_pro_builds_a_block_from_the_editor(logged_client, profile):
    response = logged_client.get(reverse("dashboard:edit", args=["blocs"]))
    assert response.status_code == 200
    body = response.content.decode()
    assert all(escape(str(t.label)) in body for t in BLOCK_TYPES.values())
    response = logged_client.post(reverse("dashboard:block_add"), {"kind": "text"})
    b = PageBlock.objects.get(profile=profile)
    assert response["Location"] == reverse("dashboard:block_edit", args=[b.pk])
    response = logged_client.post(
        reverse("dashboard:block_edit", args=[b.pk]), {"f_title": "Garanties", "f_body": "1 an"}
    )
    assert response.status_code == 302
    b.refresh_from_db()
    assert b.data["body"] == "1 an"
    response = logged_client.post(reverse("dashboard:outline_move", args=[b.key]), {"direction": "up"})
    assert response.status_code == 302


def test_pro_cannot_touch_another_page_block(logged_client):
    other = block(ProfileFactory(), "text", {"f_body": "x"})
    assert logged_client.get(reverse("dashboard:block_edit", args=[other.pk])).status_code == 404
    assert logged_client.post(reverse("dashboard:block_delete", args=[other.pk])).status_code == 404
    assert (
        logged_client.post(reverse("dashboard:outline_move", args=[other.key]), {"direction": "up"}).status_code == 404
    )
    assert logged_client.post(reverse("dashboard:outline_visible", args=["evil"]), {"visible": "1"}).status_code == 404
    assert PageBlock.objects.filter(pk=other.pk).exists()


def test_builder_requires_login(client):
    assert client.get(reverse("dashboard:edit", args=["blocs"])).status_code == 302
    assert client.post(reverse("dashboard:block_add"), {"kind": "text"}).status_code == 302


# --- team control -------------------------------------------------------------------------------


def test_moderated_block_is_hidden_and_locked(client, logged_client, profile):
    from apps.platform.models import AuditLog

    Profile = type(profile)
    Profile.objects.filter(pk=profile.pk).update(bio="x " * 60)
    b = block(profile, "text", {"f_title": "Promo", "f_body": "Texte douteux"})
    services.moderate(b, hidden=True, note="Promesse trompeuse")
    assert AuditLog.objects.filter(action="block.moderate").exists()
    _, html = page(client, profile)
    assert "Texte douteux" not in html
    body = logged_client.get(reverse("dashboard:block_edit", args=[b.pk])).content.decode()
    assert "Promesse trompeuse" in body and 'name="f_body"' not in body
    b.refresh_from_db()
    with pytest.raises(ValidationError):
        services.update_block(b, {"f_body": "contournement"}, {})


def test_admin_lists_and_moderates_blocks(admin_client):
    b = block(ProfileFactory(), "text", {"f_title": "À vérifier", "f_body": "x"})
    assert admin_client.get(reverse("admin:blocks_pageblock_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:blocks_pageblock_change", args=[b.pk])).status_code == 200
    assert admin_client.get(reverse("admin:blocks_pageblock_add")).status_code == 403
    admin_client.post(
        reverse("admin:blocks_pageblock_changelist"), {"action": "hide_blocks", "_selected_action": [b.pk]}
    )
    b.refresh_from_db()
    assert b.moderated


# --- data rights ------------------------------------------------------------------------------


def test_export_and_erasure_cover_blocks(logged_client, profile):
    from apps.profiles.services import delete_profile

    block(profile, "text_image", {"f_title": "Atelier", "f_body": "x"}, {"img_image": make_image()})
    data = json.loads(logged_client.get(reverse("dashboard:data_export")).content)
    assert data["pages"][0]["blocs"][0]["data"]["title"] == "Atelier"
    delete_profile(profile)
    assert not PageBlock.objects.filter(profile=profile).exists()
    assert not BlockImage.objects.exists()
