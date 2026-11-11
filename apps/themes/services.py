"""Site templates: resolution, validation, colour contrast, draft, publication and indexing.

Public interface (used by apps.public and the dashboard views of this app):
- resolve(profile, source="live" | "draft" | Theme) -> ResolvedTheme   (what a page renders with)
- gallery_themes(profile, category=None), can_use(profile, theme), has_premium(profile)
- start_with_theme(profile, theme), save_draft(profile, data), publish(profile)
- notification_status(profile, since)

Every colour stored or rendered is validated (#RRGGBB only): the generated stylesheet can never carry
anything else than the values below. Text colours are adjusted automatically for WCAG AA contrast.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.profiles.models import Profile

from .models import ProfileTheme, Theme

logger = logging.getLogger(__name__)

DEFAULT_THEME_CODE = "signature"
PREMIUM_ENTITLEMENT = "premium_themes"
# Path segments of /espace/modeles/ that can never be a theme code.
RESERVED_CODES = frozenset({"personnaliser", "publier", "en-ligne", "apercu", "utiliser"})

PALETTE_KEYS = ("primary", "accent", "background", "surface", "text")
SIGNATURE_PALETTE = {
    "primary": "#0A7F7D",
    "accent": "#FD6552",
    "background": "#EEF4F3",
    "surface": "#FFFFFF",
    "text": "#16242C",
}

# --- sections -------------------------------------------------------------------------------

SECTION_KEYS = ("about", "services", "gallery", "hours", "area", "links", "contact")
# Bio and services carry the page's own words (meta description, indexability): always shown.
LOCKED_SECTIONS = frozenset({"about", "services"})
SECTION_LABELS = {
    "about": gettext_lazy("Présentation"),
    "services": gettext_lazy("Prestations"),
    "gallery": gettext_lazy("Réalisations"),
    "hours": gettext_lazy("Horaires"),
    "area": gettext_lazy("Zone et adresse"),
    "links": gettext_lazy("Liens"),
    "contact": gettext_lazy("Contact"),
}
# Headings that read naturally for each trade family (same structure, same SEO).
CATEGORY_LABELS = {
    "restauration": {"services": gettext_lazy("La carte"), "gallery": gettext_lazy("En images")},
    "beaute": {"services": gettext_lazy("Soins et tarifs")},
    "mode": {"services": gettext_lazy("Créations et services"), "gallery": gettext_lazy("Collection")},
    "tech_freelance": {"services": gettext_lazy("Ce que je fais"), "gallery": gettext_lazy("Projets")},
    "sante": {"services": gettext_lazy("Consultations et soins")},
    "conseil_juridique": {"services": gettext_lazy("Domaines d'intervention")},
    "commerce": {"services": gettext_lazy("Produits et services"), "gallery": gettext_lazy("La boutique")},
    "evenementiel_photo": {"services": gettext_lazy("Formules"), "gallery": gettext_lazy("Portfolio")},
    "education": {"services": gettext_lazy("Cours et formations")},
}


def section_label(key: str, category: str = "") -> str:
    return str(CATEGORY_LABELS.get(category, {}).get(key) or SECTION_LABELS[key])


def normalize_sections(value) -> list[dict]:
    """Known keys in the given order (duplicates dropped), missing keys appended; locked ones visible."""
    seen: dict[str, bool] = {}
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            key, visible = item.get("key"), item.get("visible", True)
        else:
            key, visible = item, True
        if key in SECTION_KEYS and key not in seen:
            seen[key] = bool(visible) or key in LOCKED_SECTIONS
    for key in SECTION_KEYS:
        seen.setdefault(key, True)
    return [{"key": key, "visible": visible} for key, visible in seen.items()]


# --- fonts, corners, layouts ------------------------------------------------------------------

SYSTEM_STACK = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
FONT_PAIRS = {
    "archivo": {
        "label": gettext_lazy("Archivo (Modulis)"),
        "head": f'"Archivo", {SYSTEM_STACK}',
        "body": f'"Archivo", {SYSTEM_STACK}',
        "weight": "800",
        "tracking": "-0.02em",
        "webfont": True,
    },
    "system": {
        "label": gettext_lazy("Moderne"),
        "head": SYSTEM_STACK,
        "body": SYSTEM_STACK,
        "weight": "800",
        "tracking": "-0.015em",
    },
    "serif": {
        "label": gettext_lazy("Élégante (serif)"),
        "head": '"Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, "Noto Serif", serif',
        "body": SYSTEM_STACK,
        "weight": "600",
        "tracking": "-0.01em",
    },
    "humanist": {
        "label": gettext_lazy("Douce (humaniste)"),
        "head": 'Seravek, "Gill Sans Nova", Ubuntu, Calibri, "DejaVu Sans", source-sans-pro, sans-serif',
        "body": 'Seravek, "Gill Sans Nova", Ubuntu, Calibri, "DejaVu Sans", source-sans-pro, sans-serif',
        "weight": "700",
        "tracking": "0",
    },
    "geometric": {
        "label": gettext_lazy("Géométrique"),
        "head": 'Avenir, Montserrat, Corbel, "URW Gothic", source-sans-pro, sans-serif',
        "body": SYSTEM_STACK,
        "weight": "700",
        "tracking": "-0.01em",
    },
    "mono": {
        "label": gettext_lazy("Technique (mono)"),
        "head": 'ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, "DejaVu Sans Mono", monospace',
        "body": SYSTEM_STACK,
        "weight": "700",
        "tracking": "-0.02em",
    },
    "rounded": {
        "label": gettext_lazy("Arrondie"),
        "head": 'ui-rounded, "Hiragino Maru Gothic ProN", Quicksand, Comfortaa, Manjari, "Arial Rounded MT", '
        '"Arial Rounded MT Bold", Calibri, source-sans-pro, sans-serif',
        "body": SYSTEM_STACK,
        "weight": "800",
        "tracking": "0",
    },
}
CORNERS = {
    "rounded": {"label": gettext_lazy("Arrondis"), "lg": "22px", "md": "14px", "sm": "10px"},
    "soft": {"label": gettext_lazy("Légers"), "lg": "12px", "md": "8px", "sm": "6px"},
    "sharp": {"label": gettext_lazy("Droits"), "lg": "2px", "md": "2px", "sm": "0"},
}
# Avatar display size per layout (px): the photo srcset never downloads more than needed.
PHOTO_DISPLAY = {"split_photo": (320, 800), "editorial": (280, 800), "magazine": (480, 800)}
LAYOUTS = tuple(Theme.Layout.values)
CTA_MAX = 40


# --- colours & contrast (WCAG 2.x) ------------------------------------------------------------

AA = 4.5
WHITE, INK = "#FFFFFF", "#111111"


def is_hex(value) -> bool:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def _rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c))) for c in rgb))


def luminance(value: str) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """t = 0 → a, t = 1 → b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb, strict=True)))


def readable_on(background: str) -> str:
    """White or near-black, whichever reads best on `background` (one of them always passes AA)."""
    for candidate in sorted((WHITE, INK), key=lambda c: -contrast(c, background)):
        if contrast(candidate, background) >= AA:
            return candidate
    return "#000000" if contrast("#000000", background) >= contrast(WHITE, background) else WHITE


def ensure_contrast(color: str, backgrounds: list[str], target: float = AA) -> str:
    """`color` darkened (light backgrounds) or lightened (dark ones) until it passes on every background."""

    def worst(c: str) -> float:
        return min(contrast(c, bg) for bg in backgrounds)

    if worst(color) >= target:
        return color
    dark_bg = sum(luminance(bg) for bg in backgrounds) / len(backgrounds) < 0.18
    towards = "#FFFFFF" if dark_bg else "#000000"
    for step in range(1, 21):
        candidate = mix(color, towards, step / 20)
        if worst(candidate) >= target:
            return candidate
    return readable_on(backgrounds[0])


def clean_palette(value, base: dict | None = None) -> dict:
    """A complete, valid palette: invalid or missing keys fall back to `base`, then to Signature."""
    base = base or SIGNATURE_PALETTE
    value = value if isinstance(value, dict) else {}
    out = {}
    for key in PALETTE_KEYS:
        candidate = value.get(key)
        fallback = base.get(key) if is_hex(base.get(key)) else SIGNATURE_PALETTE[key]
        out[key] = candidate.upper() if is_hex(candidate) else fallback.upper()
    return out


def derive_tokens(palette: dict) -> dict:
    """CSS custom properties of a page, every text colour checked for AA on its background."""
    p = clean_palette(palette)
    bg, surface = p["background"], p["surface"]
    dark = luminance(bg) < 0.18
    text = ensure_contrast(p["text"], [bg, surface])
    muted = ensure_contrast(mix(text, surface, 0.35), [bg, surface])
    primary = p["primary"]
    accent = p["accent"]
    return {
        "primary": primary,
        "on-primary": readable_on(primary),
        "primary-ink": ensure_contrast(primary, [bg, surface]),  # primary used as text/links
        "accent": accent,
        "on-accent": readable_on(accent),
        "accent-ink": ensure_contrast(accent, [bg, surface], 3.0),  # large/decorative text only
        "bg": bg,
        "surface": surface,
        "text": text,
        "muted": muted,
        "line": mix(surface, text, 0.16 if dark else 0.12),
        "soft": mix(surface, primary, 0.14 if dark else 0.08),
        "on-soft": ensure_contrast(text, [mix(surface, primary, 0.14 if dark else 0.08)]),
        "scheme": "dark" if dark else "light",
    }


# --- resolution -----------------------------------------------------------------------------


def _fallback_theme() -> Theme:
    """Unsaved Signature theme: pages keep rendering even if the catalogue is empty."""
    return Theme(
        code=DEFAULT_THEME_CODE,
        name="Modulis Signature",
        category=Theme.Category.UNIVERSEL,
        layout=Theme.Layout.COVER_COLOR,
        palette=dict(SIGNATURE_PALETTE),
        font_pair="archivo",
        corners="rounded",
        sections=list(SECTION_KEYS),
        cta_label="",
    )


def default_theme() -> Theme:
    try:
        with transaction.atomic():
            theme = Theme.objects.filter(code=DEFAULT_THEME_CODE).first()
    except DatabaseError:  # table missing (tests without migrations, broken deploy): never break pages
        theme = None
    return theme or _fallback_theme()


def get_theme(code: str) -> Theme | None:
    if not code:
        return None
    return Theme.objects.filter(code=code).first()


def settings_for(profile: Profile) -> ProfileTheme | None:
    try:
        with transaction.atomic():
            return ProfileTheme.objects.select_related("theme").filter(profile=profile).first()
    except DatabaseError:
        logger.warning("ProfileTheme lookup failed for profile %s", profile.pk)
        return None


@dataclass
class ResolvedTheme:
    theme: Theme
    layout: str
    palette: dict
    font_pair: str
    corners: str
    sections: list[dict]
    cta_label: str
    version_seed: str = ""
    tokens: dict = field(default_factory=dict)

    def __post_init__(self):
        self.tokens = derive_tokens(self.palette)

    @property
    def font(self) -> dict:
        return FONT_PAIRS[self.font_pair]

    @property
    def template(self) -> str:
        return f"public/themes/{self.layout}.html"

    @property
    def uses_webfont(self) -> bool:
        return bool(self.font.get("webfont"))

    def css(self) -> str:
        t, font, radius = self.tokens, self.font, CORNERS[self.corners]
        props = [
            *(f"--c-{name}:{t[name]}" for name in t if name != "scheme"),
            f"--r-lg:{radius['lg']}",
            f"--r-md:{radius['md']}",
            f"--r-sm:{radius['sm']}",
            f"--f-head:{font['head']}",
            f"--f-body:{font['body']}",
            f"--f-head-weight:{font['weight']}",
            f"--f-head-tracking:{font['tracking']}",
            f"color-scheme:{t['scheme']}",
        ]
        return "/* Modulis — theme " + self.theme.code + " */\n:root{" + ";".join(props) + "}\n"

    @property
    def version(self) -> str:
        payload = f"{self.css()}|{self.layout}|{self.version_seed}"
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def visible_sections(self) -> list[str]:
        return [s["key"] for s in self.sections if s["visible"]]


def _resolved(theme: Theme, data: dict, *, version_seed: str = "") -> ResolvedTheme:
    data = data or {}
    font = data.get("font_pair") or theme.font_pair
    corners = data.get("corners") or theme.corners
    layout = data.get("hero_variant") or theme.layout
    return ResolvedTheme(
        theme=theme,
        layout=layout if layout in LAYOUTS else Theme.Layout.COVER_COLOR,
        palette=clean_palette(data.get("palette") or {}, base=clean_palette(theme.palette)),
        font_pair=font if font in FONT_PAIRS else "system",
        corners=corners if corners in CORNERS else "rounded",
        sections=normalize_sections(data.get("sections") or theme.sections),
        cta_label=(data.get("cta_label") or theme.cta_label or "")[:CTA_MAX],
        version_seed=version_seed,
    )


def theme_defaults(theme: Theme) -> dict:
    return {
        "theme": theme.code,
        "palette": clean_palette(theme.palette),
        "font_pair": theme.font_pair if theme.font_pair in FONT_PAIRS else "system",
        "corners": theme.corners if theme.corners in CORNERS else "rounded",
        "hero_variant": theme.layout,
        "cta_label": theme.cta_label,
        "sections": normalize_sections(theme.sections),
    }


def live_data(pt: ProfileTheme) -> dict:
    return {
        "theme": pt.theme.code,
        "palette": pt.palette,
        "font_pair": pt.font_pair,
        "corners": pt.corners,
        "hero_variant": pt.hero_variant,
        "cta_label": pt.cta_label,
        "sections": pt.sections,
    }


def resolve(profile: Profile, source="live") -> ResolvedTheme:
    """Settings a page renders with: the live ones, the draft (preview) or a theme's defaults."""
    if isinstance(source, Theme):
        return _resolved(source, theme_defaults(source), version_seed="preview")
    pt = settings_for(profile)
    if pt is None:
        theme = default_theme()
        data = theme_defaults(theme)
        if theme.code == DEFAULT_THEME_CODE and is_hex(profile.cover_color):
            data["palette"] = {**data["palette"], "primary": profile.cover_color}  # colour chosen at onboarding
        return _resolved(theme, data)
    if source == "draft" and pt.draft:
        theme = get_theme(pt.draft.get("theme")) or pt.theme
        return _resolved(theme, pt.draft, version_seed="draft")
    return _resolved(pt.theme, live_data(pt), version_seed=str(pt.published_version))


# --- entitlements & gallery -----------------------------------------------------------------


def has_premium(profile: Profile) -> bool:
    try:
        from apps.billing.services import has
    except ImportError:  # pragma: no cover - billing is always installed
        return False
    try:
        with transaction.atomic():
            return bool(has(profile, PREMIUM_ENTITLEMENT))
    except (DatabaseError, LookupError) as exc:
        logger.warning("premium_themes lookup failed for profile %s: %s", profile.pk, exc.__class__.__name__)
        return False


def can_use(profile: Profile, theme: Theme, *, premium: bool | None = None) -> bool:
    if not theme.is_active:
        return False
    if not theme.is_premium:
        return True
    return has_premium(profile) if premium is None else premium


def gallery_themes(category: str | None = None):
    qs = Theme.objects.filter(is_active=True).order_by("order", "name")
    if category:
        qs = qs.filter(category=category)
    return qs


class ThemeError(Exception):
    """A business rule refused the action (message is user-facing)."""


def themes_enabled() -> bool:
    from apps.platform.services import feature

    return feature("themes")


def _get_or_create_settings(profile: Profile) -> ProfileTheme:
    pt = ProfileTheme.objects.select_for_update().select_related("theme").filter(profile=profile).first()
    if pt is not None:
        return pt
    theme = default_theme()
    if theme.pk is None:
        raise ThemeError(_("Les modèles ne sont pas encore installés."))
    data = theme_defaults(theme)
    if is_hex(profile.cover_color):
        data["palette"]["primary"] = profile.cover_color.upper()
    return ProfileTheme.objects.create(
        profile=profile,
        theme=theme,
        palette=data["palette"],
        font_pair=data["font_pair"],
        corners=data["corners"],
        hero_variant=data["hero_variant"],
        cta_label=data["cta_label"],
        sections=data["sections"],
    )


def _check_usable(profile: Profile, theme: Theme) -> None:
    if not theme.is_active:
        raise ThemeError(_("Ce modèle n'est plus disponible."))
    if theme.is_premium and not has_premium(profile):
        raise ThemeError(_("Ce modèle est réservé aux offres Essentiel et Pro."))


@transaction.atomic
def start_with_theme(profile: Profile, theme: Theme) -> ProfileTheme:
    """“Utiliser ce modèle”: the draft becomes this theme with its professional defaults."""
    if not themes_enabled():
        raise ThemeError(_("Le choix des modèles est momentanément indisponible."))
    pt = _get_or_create_settings(profile)
    if theme.pk == pt.theme_id:  # back to the live theme: start from its live customisations
        pt.draft = {**live_data(pt), "palette": clean_palette(pt.palette, base=clean_palette(theme.palette))}
    else:
        _check_usable(profile, theme)
        pt.draft = theme_defaults(theme)
    pt.draft_updated_at = timezone.now()
    pt.save(update_fields=["draft", "draft_updated_at", "updated_at"])
    return pt


def current_draft(profile: Profile) -> dict:
    """The draft to edit: the saved draft, else a copy of the live settings."""
    pt = settings_for(profile)
    if pt is None:
        theme = default_theme()
        data = theme_defaults(theme)
        if is_hex(profile.cover_color):
            data["palette"]["primary"] = profile.cover_color.upper()
        return data
    if pt.draft and get_theme(pt.draft.get("theme")):
        return pt.draft
    return {**live_data(pt), "palette": clean_palette(pt.palette, base=clean_palette(pt.theme.palette))}


def clean_draft(theme: Theme, data: dict) -> dict:
    """Validate customisations; raises ValidationError with a plain-language message."""
    palette = data.get("palette") or {}
    if not isinstance(palette, dict) or any(not is_hex(palette.get(k)) for k in PALETTE_KEYS):
        raise ValidationError(_("Choisis des couleurs valides (format #RRGGBB)."))
    font = data.get("font_pair")
    if font not in FONT_PAIRS:
        raise ValidationError(_("Choisis une typographie de la liste."))
    corners = data.get("corners")
    if corners not in CORNERS:
        raise ValidationError(_("Choisis un style d'angles de la liste."))
    hero = data.get("hero_variant")
    if hero not in LAYOUTS:
        raise ValidationError(_("Choisis un en-tête de la liste."))
    cta = " ".join(str(data.get("cta_label") or "").split())
    if len(cta) > CTA_MAX:
        raise ValidationError(_("Le texte du bouton doit faire %(n)d caractères au plus.") % {"n": CTA_MAX})
    return {
        "theme": theme.code,
        "palette": clean_palette(palette),
        "font_pair": font,
        "corners": corners,
        "hero_variant": hero,
        "cta_label": cta,
        "sections": normalize_sections(data.get("sections")),
    }


@transaction.atomic
def save_draft(profile: Profile, data: dict) -> ProfileTheme:
    if not themes_enabled():
        raise ThemeError(_("Le choix des modèles est momentanément indisponible."))
    pt = _get_or_create_settings(profile)
    theme = get_theme((pt.draft or {}).get("theme")) or pt.theme
    clean = clean_draft(theme, data)
    pt.draft = clean
    pt.draft_updated_at = timezone.now()
    pt.save(update_fields=["draft", "draft_updated_at", "updated_at"])
    return pt


# --- publication ----------------------------------------------------------------------------


@dataclass
class PublishResult:
    profile: Profile
    version: int
    indexable: bool
    blockers: list[str]
    instant: bool  # search engines notified right now (flush_now enqueued)


def seo_readiness(profile: Profile) -> dict:
    from apps.profiles.services import completeness_items, compute_completeness, indexability_blockers

    profile.completeness_score = compute_completeness(profile)
    blockers = indexability_blockers(profile)
    return {
        "score": profile.completeness_score,
        "items": completeness_items(profile),
        "blockers": blockers,
        "indexable": not blockers,
        "public": profile.is_publicly_visible,
    }


def _instant_publish_enabled() -> bool:
    from apps.platform.services import feature

    return feature("instant_publish") and feature("indexing")


def publish(profile: Profile) -> PublishResult:
    """“Valider et publier”: draft → live, new stylesheet version, content date bumped, engines notified.

    Runs inside the caller's transaction (ATOMIC_REQUESTS); the indexing work happens on commit.
    """
    from apps.profiles.services import refresh_seo_state
    from apps.seo.indexing import queue_urls, related_urls

    if not themes_enabled():
        raise ThemeError(_("Le choix des modèles est momentanément indisponible."))
    with transaction.atomic():
        pt = _get_or_create_settings(profile)
        theme = get_theme((pt.draft or {}).get("theme")) or pt.theme
        _check_usable(profile, theme)
        data = clean_draft(theme, pt.draft or live_data(pt))
        pt.theme = theme
        pt.palette = data["palette"]
        pt.font_pair = data["font_pair"]
        pt.corners = data["corners"]
        pt.hero_variant = data["hero_variant"]
        pt.cta_label = data["cta_label"]
        pt.sections = data["sections"]
        pt.draft = {}
        pt.published_at = timezone.now()
        pt.published_version += 1
        pt.save()

    # The page HTML changed: new content date (sitemap lastmod) and indexing state recomputed.
    profile = refresh_seo_state(profile, content_changed=True)
    indexable = profile.is_indexable
    instant = False
    if indexable:
        urls = [profile.absolute_url, *related_urls(profile)]
        transaction.on_commit(lambda: queue_urls(urls))
        if _instant_publish_enabled():
            instant = True
            transaction.on_commit(_flush_now)
    from apps.profiles.services import indexability_blockers

    return PublishResult(
        profile=profile,
        version=pt.published_version,
        indexable=indexable,
        blockers=[] if indexable else indexability_blockers(profile),
        instant=instant,
    )


def _flush_now() -> None:
    from apps.seo.tasks import flush_now

    try:
        flush_now()
    except Exception:  # the periodic flush will catch up: publication never fails because of a queue
        logger.exception("flush_now could not be enqueued")


def notification_status(profile: Profile, since=None) -> dict:
    """What happened to the search-engine notification of this page since `since` (publication)."""
    from apps.platform.services import feature
    from apps.seo.models import IndexingLog, IndexingQueue

    url = profile.absolute_url
    if not profile.is_indexable:
        return {"state": "not_indexable", "final": True}
    if not (feature("indexing") and settings.KLIZ_ENABLED):
        return {"state": "disabled", "final": True}
    logs = IndexingLog.objects.order_by("-created_at")
    if since is not None:
        logs = logs.filter(created_at__gte=since)
    for log in logs[:50]:
        if url in (log.urls or []) or log.sample_url == url:
            return {
                "state": "sent" if log.success else "retry",
                "provider": log.provider,
                "at": log.created_at,
                "final": True,
            }
    if IndexingQueue.objects.filter(url=url).exists():
        return {"state": "queued", "final": False}
    stale = since is not None and timezone.now() - since > STATUS_POLL_WINDOW
    return {"state": "pending", "final": stale}


STATUS_POLL_WINDOW = timedelta(minutes=2)
