"""2026 site design: open-now state, bio lede, lightbox markup, every layout with/without photo, page budget."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.staticfiles import finders
from django.utils import timezone

from apps.profiles.models import Profile, ProfileMedia
from apps.public.views import _hours, initials, name_fit, opening_state, split_bio
from apps.seo.tests.utils import indexable_profile
from apps.themes import services
from apps.themes.models import ProfileTheme, Theme

pytestmark = pytest.mark.django_db

INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/ld\+json)[^>]*>", re.I)
WEEK = {day: [["08:00", "18:00"]] for day in ("mo", "tu", "we", "th", "fr")}
PAGE_BUDGET = 120_000  # HTML + CSS + JS of a page, photos and fonts excluded
JS_BUDGET = 8 * 1024


def douala(year, month, day, hour, minute=0):
    """An aware datetime given in Douala time (UTC+1)."""
    return datetime(year, month, day, hour - 1, minute, tzinfo=UTC)


# 2026-11-09 is a Monday.
MONDAY, SATURDAY, SUNDAY = 9, 14, 15


# --- open now -------------------------------------------------------------------------------


def test_open_now_during_opening_hours():
    state = opening_state(WEEK, douala(2026, 11, MONDAY, 10, 30))
    assert state["open"] and str(state["label"]) == "Ouvert maintenant" and state["detail"] == "Ferme à 18:00"


def test_closed_before_opening_today():
    state = opening_state(WEEK, douala(2026, 11, MONDAY, 7, 15))
    assert not state["open"] and state["detail"] == "Ouvre à 08:00"


def test_closed_after_closing_opens_tomorrow():
    state = opening_state(WEEK, douala(2026, 11, MONDAY, 18, 0))  # closing time is excluded
    assert not state["open"] and state["detail"] == "Ouvre demain à 08:00"


def test_closed_weekend_opens_on_monday():
    state = opening_state(WEEK, douala(2026, 11, SATURDAY, 12))
    assert not state["open"] and state["detail"] == "Ouvre lundi à 08:00"
    assert opening_state(WEEK, douala(2026, 11, SUNDAY, 12))["detail"] == "Ouvre demain à 08:00"


def test_open_now_uses_douala_time_not_utc():
    # 17:30 UTC = 18:30 in Douala: already closed, although 17:30 is inside the range.
    assert not opening_state(WEEK, datetime(2026, 11, MONDAY, 17, 30, tzinfo=UTC))["open"]
    # 07:30 UTC = 08:30 in Douala: open.
    assert opening_state(WEEK, datetime(2026, 11, MONDAY, 7, 30, tzinfo=UTC))["open"]


def test_split_ranges_and_no_hours():
    hours = {"mo": [["08:00", "12:00"], ["14:00", "18:00"]]}
    lunch = opening_state(hours, douala(2026, 11, MONDAY, 13))
    assert not lunch["open"] and lunch["detail"] == "Ouvre à 14:00"
    assert opening_state(hours, douala(2026, 11, MONDAY, 15))["detail"] == "Ferme à 18:00"
    assert opening_state({}, timezone.now()) is None
    assert opening_state({"mo": [["bad"]]}, timezone.now()) is None
    assert opening_state("garbage", timezone.now()) is None


def test_hours_rows_flag_today():
    profile = Profile(opening_hours={"mo": [["08:00", "12:00"], ["14:00", "18:00"]]})
    rows = _hours(profile, douala(2026, 11, MONDAY, 9))
    assert [r["key"] for r in rows] == ["mo", "tu", "we", "th", "fr", "sa", "su"]
    assert rows[0]["today"] and not any(r["today"] for r in rows[1:])
    assert rows[0]["data"] == "08:00-12:00,14:00-18:00" and rows[1]["ranges"] == ""


def test_open_state_is_rendered_and_refreshable(client):
    profile = indexable_profile(opening_hours=WEEK)
    html = client.get(f"/{profile.slug}").content.decode()
    assert html.count("data-open-state") >= 2  # hero chip + hours section
    assert 'data-l-closes="Ferme à {t}"' in html and 'data-ranges="08:00-18:00"' in html
    assert '<th scope="row" data-today="Aujourd\'hui">Lundi</th>' in html and html.count("is-today") == 1


# --- bio lede, initials -----------------------------------------------------------------------


def test_bio_lede_is_the_first_clean_sentence():
    lede, rest = split_bio("Plombier à Douala depuis 2012, j'interviens partout en ville. Devis gratuit.\nMerci.")
    assert lede == "Plombier à Douala depuis 2012, j'interviens partout en ville."
    assert rest == "Devis gratuit.\nMerci."
    assert split_bio("Court. Puis la suite du texte.") == ("", "Court. Puis la suite du texte.")
    assert split_bio("Une seule phrase sans point final assez longue pour un chapeau")[0] == ""
    assert initials("Chez Mama Ngono") == "CM" and initials("d'Artagnan") == "DA" and initials("") == "·"


# --- lightbox ---------------------------------------------------------------------------------


def add_gallery(profile, n=3):
    for i in range(n):
        ProfileMedia.objects.create(
            profile=profile,
            image=f"profiles/{profile.pk}/gallery/{i}.webp",
            width=1200,
            height=900,
            caption=f"Photo {i}",
        )


def test_lightbox_markup_is_accessible(client):
    profile = indexable_profile()
    add_gallery(profile)
    html = client.get(f"/{profile.slug}").content.decode()
    dialog = re.search(r"<dialog[^>]*>.*?</dialog>", html, re.S).group(0)
    assert 'aria-label="Photos en grand"' in dialog and "data-lightbox" in dialog
    for label in ("Fermer", "Photo précédente", "Photo suivante"):
        assert re.search(rf'<button class="t-lightbox__btn[^"]*" type="button" aria-label="{label}"', dialog)
    assert 'aria-live="polite"' in dialog
    assert '<img class="t-lightbox__img"' in dialog and 'alt="Photo 0"' in dialog and 'loading="lazy"' in dialog
    links = re.findall(r'<a class="t-gallery__link" href="([^"]+)" data-lb="(\d)"', html)
    assert [i for _href, i in links] == ["0", "1", "2"]
    assert all(href.startswith("/media/profiles/") for href, _i in links)  # works without JS
    assert html.count('<span class="t-sr">(agrandir)</span>') == 3


def test_no_lightbox_without_gallery(client):
    profile = indexable_profile()
    assert "<dialog" not in client.get(f"/{profile.slug}").content.decode()


# --- every layout, with and without photo ---------------------------------------------------


def use_layout(profile, layout):
    theme = Theme.objects.filter(layout=layout).first()
    pt = services.assign_theme(profile, theme)
    assert pt.hero_variant == layout
    return theme


@pytest.mark.parametrize("photo", [True, False], ids=["photo", "no-photo"])
@pytest.mark.parametrize("layout", list(services.LAYOUTS))
def test_every_layout_renders_with_and_without_photo(client, layout, photo):
    profile = indexable_profile(opening_hours=WEEK, email_public="paul@exemple.test", address="Rue 12")
    add_gallery(profile, 2)
    if photo:
        Profile.objects.filter(pk=profile.pk).update(photo=f"profiles/{profile.pk}/photo.webp")
    theme = use_layout(profile, layout)
    response = client.get(f"/{profile.slug}")
    html = response.content.decode()
    assert response.status_code == 200
    assert f"t--{layout}" in html and ("has-photo" if photo else "no-photo") in html
    assert html.count("<h1") == 1
    assert ('<img class="profile-head__photo"' in html) is photo
    if not photo:  # a designed composition, never an empty box
        assert any(art in html for art in ('class="t-art"', "t-sig__slab", "t-card__initials"))
        assert f">{initials(profile.display_name)}<" in html
    assert " style=" not in html and not INLINE_SCRIPT_RE.search(html)
    assert 'id="contact"' in html and 'id="horaires"' in html and 'id="realisations"' in html
    assert "/static/js/site-motion.js" in html and 'src="/static/js/profile.js" defer' in html
    font = services.FONT_PAIRS[theme.font_pair]
    if font.get("webfont"):
        assert re.search(r'<link rel="preload" href="[^"]+\.woff2" as="font" type="font/woff2" crossorigin>', html)


# --- budgets ----------------------------------------------------------------------------------


def static_bytes(path: str) -> int:
    found = finders.find(path)
    assert found, path
    return Path(found).stat().st_size


@pytest.mark.parametrize("layout", list(services.LAYOUTS))
def test_page_weight_budget(client, layout):
    profile = indexable_profile(opening_hours=WEEK, email_public="paul@exemple.test", address="Rue 12")
    add_gallery(profile, 6)
    for i in range(8):
        profile.services.create(
            title=f"Prestation {i}", description="Détail de la prestation", price_label="5 000 FCFA"
        )
    theme = use_layout(profile, layout)
    html = client.get(f"/{profile.slug}").content
    css_url = re.search(rb'href="(/[^"]+/theme\.css\?v=\w+)"', html).group(1).decode()
    resolved = services.resolve(profile)
    assets = [
        "css/themes/base.css",
        f"css/themes/{layout}.css",
        "js/profile.js",
        "js/site-motion.js",
        *([resolved.font_css] if resolved.font_css else []),
    ]
    total = len(html) + len(client.get(css_url).content) + sum(static_bytes(a) for a in assets)
    assert total < PAGE_BUDGET, f"{theme.code}: {total} bytes"
    assert static_bytes("js/site-motion.js") < JS_BUDGET


@pytest.mark.parametrize("pair", [k for k, v in services.FONT_PAIRS.items() if v.get("webfont")])
def test_each_font_pair_loads_at_most_two_files(pair):
    font = services.FONT_PAIRS[pair]
    css = Path(finders.find(font["css"])).read_text(encoding="utf-8")
    files = set(re.findall(r'url\("([^"]+\.woff2)"\)', css))
    # fonts.css (brand) also declares a latin-ext face, only fetched for those characters (unicode-range)
    latin = {f for f in files if "latin-ext" not in f}
    assert 1 <= len(latin) <= 2
    assert "font-display:swap" in css.replace(" ", "")
    assert finders.find(font["preload"])
    assert Path(settings.BASE_DIR, "static", font["preload"]).name in " ".join(files)


# --- catalogue, tokens ------------------------------------------------------------------------


def test_catalogue_uses_every_layout_and_new_fonts():
    themes_ = list(Theme.objects.all())
    assert {t.layout for t in themes_} == set(services.LAYOUTS)
    assert {"archivo", "fraunces", "instrument", "bricolage"} <= {t.font_pair for t in themes_}
    premium = {t.code for t in themes_ if t.is_premium}
    assert premium == {"saveur", "atelier", "cabinet", "objectif", "prestige"}


@pytest.mark.parametrize("code", ["signature", "code", "objectif", "prestige", "eclat", "saveur"])
def test_small_accent_text_is_aa(code):
    tokens = services.derive_tokens(Theme.objects.get(code=code).palette)
    for bg in (tokens["bg"], tokens["surface"]):
        assert services.contrast(tokens["accent-text"], bg) >= 4.5
    css = services.resolve(indexable_profile(), Theme.objects.get(code=code)).css()
    assert "--c-accent-text:" in css and "--f-head-vary:" in css


def test_assign_theme_publishes_defaults():
    profile = indexable_profile()
    theme = Theme.objects.get(code="eclat")
    pt = services.assign_theme(profile, theme)
    again = services.assign_theme(profile, theme)
    assert ProfileTheme.objects.filter(profile=profile).count() == 1
    assert again.published_version == pt.published_version + 1 and again.font_pair == "instrument"
    assert services.resolve(profile).layout == "card"


# --- headline fitting, dock, section order --------------------------------------------------


@pytest.mark.parametrize(
    ("name", "fit"),
    [
        ("Paul Eto", ""),
        ("Ange Kenmogne", "m"),
        ("Fotso Bâtiment", "m"),
        ("Studio Lumière Kribi", "s"),
        ("Établissements Nkoulou", "xs"),
        ("", ""),
    ],
)
def test_name_fit_steps_down_long_words(name, fit):
    assert name_fit(name) == fit


def test_long_name_gets_a_fitted_title_and_a_contact_dock(client):
    profile = indexable_profile(display_name="Établissements Nkoulou", whatsapp="+237690000001")
    use_layout(profile, "cover_color")
    html = client.get(f"/{profile.slug}").content.decode()
    assert 'class="profile-head__name t-name t-name--xs"' in html
    assert 'class="t-dock"' in html  # visible without JS; site-motion.js hides it near the hero buttons


def test_contact_closes_every_default_page():
    for theme in Theme.objects.all():
        assert list(theme.sections)[-1] == "contact", theme.code
