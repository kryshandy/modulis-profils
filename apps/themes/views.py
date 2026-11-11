"""Espace pro › Modèles: gallery, live preview, customizer, “Valider et publier”, success screen.

Every view works on `request.profile` (set by profile_required from the logged-in user's own pages):
no profile id ever travels in a URL, so there is nothing to tamper with (no IDOR).
"""

from __future__ import annotations

from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST, require_safe
from django_ratelimit.decorators import ratelimit

from apps.dashboard.views.common import dash_render, profile_required
from apps.public.http import set_private_no_store
from apps.public.views import render_profile_page, theme_css_response

from . import forms, services
from .models import Theme

FRAME_SELF = {"frame-src": ["'self'"]}  # dashboard pages that embed the preview iframe


def _embeds_preview(response):
    response._csp_update = FRAME_SELF
    return response


def _frameable(response):
    """The preview may be shown in an iframe of the dashboard only (same origin), never indexed or cached."""
    response["X-Frame-Options"] = "SAMEORIGIN"
    response._csp_replace = {"frame-ancestors": ["'self'"]}
    response["X-Robots-Tag"] = "noindex, nofollow"
    return set_private_no_store(response)


def _active_theme(code: str) -> Theme:
    theme = Theme.objects.filter(code=code, is_active=True).first()
    if theme is None:
        raise Http404
    return theme


def _back_to_gallery(request, message: str):
    messages.error(request, message)
    return redirect("themes:gallery")


# --- gallery ----------------------------------------------------------------------------------


@require_safe
@profile_required
def gallery(request):
    profile = request.profile
    enabled = services.themes_enabled()
    category = request.GET.get("categorie", "")
    if category not in Theme.Category.values:
        category = ""
    live = services.resolve(profile)
    pt = services.settings_for(profile)
    draft_code = (pt.draft or {}).get("theme") if pt else ""
    premium = services.has_premium(profile)
    all_themes = list(services.gallery_themes())
    counts: dict[str, int] = {}
    for theme in all_themes:
        counts[theme.category] = counts.get(theme.category, 0) + 1
    cards = [
        {
            "theme": theme,
            "is_current": theme.code == live.theme.code,
            "is_draft": bool(draft_code) and theme.code == draft_code and theme.code != live.theme.code,
            "locked": theme.is_premium and not premium,
        }
        for theme in all_themes
        if not category or theme.category == category
    ]
    context = {
        "enabled": enabled,
        "cards": cards,
        "category": category,
        "categories": [
            (value, label, counts.get(value, 0)) for value, label in Theme.Category.choices if counts.get(value)
        ],
        "total": len(all_themes),
        "live": live,
        "has_premium": premium,
        "has_draft": bool(draft_code),
    }
    return dash_render(request, "themes/gallery.html", context)


@require_safe
@profile_required
def detail(request, code):
    theme = _active_theme(code)
    profile = request.profile
    context = {
        "theme": theme,
        "locked": theme.is_premium and not services.has_premium(profile),
        "enabled": services.themes_enabled(),
        "preview_url": reverse("themes:preview", kwargs={"code": theme.code}),
        "is_current": services.resolve(profile).theme.code == theme.code,
    }
    return _embeds_preview(dash_render(request, "themes/detail.html", context))


@require_safe
@profile_required
def preview(request, code):
    """The user's OWN page rendered with this theme's defaults (private, noindex, frameable by us only)."""
    theme = _active_theme(code)
    resolved = services.resolve(request.profile, theme)
    css_url = reverse("themes:preview_css", kwargs={"code": theme.code}) + f"?v={resolved.version}"
    response = render_profile_page(
        request, request.profile, owner_private=False, theme=resolved, stylesheet_url=css_url, preview=True
    )
    return _frameable(response)


@require_safe
@profile_required
def preview_css(request, code):
    theme = _active_theme(code)
    return _frameable(theme_css_response(services.resolve(request.profile, theme).css()))


@require_POST
@profile_required
def use(request, code):
    theme = _active_theme(code)
    try:
        services.start_with_theme(request.profile, theme)
    except services.ThemeError as exc:
        return _back_to_gallery(request, str(exc))
    messages.success(request, _("Modèle « %(name)s » choisi : personnalise-le, puis publie.") % {"name": theme.name})
    return redirect("themes:customize")


# --- customizer -------------------------------------------------------------------------------


def _wants_json(request) -> bool:
    return request.headers.get("X-Requested-With") == "theme-editor"


def _draft_preview_url(profile) -> str:
    return reverse("themes:draft_preview") + f"?v={services.resolve(profile, 'draft').version}"


@require_http_methods(["GET", "HEAD", "POST"])
@profile_required
def customize(request):
    profile = request.profile
    if not services.themes_enabled():
        return _back_to_gallery(request, _("Le choix des modèles est momentanément indisponible."))
    draft = services.current_draft(profile)
    theme = services.get_theme(draft.get("theme")) or services.default_theme()
    error = ""
    if request.method == "POST":
        data = forms.draft_from_post(request.POST, theme, draft)
        try:
            services.save_draft(profile, data)
        except (ValidationError, services.ThemeError) as exc:
            error = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
            if _wants_json(request):
                return JsonResponse({"ok": False, "error": error}, status=400)
        else:
            if _wants_json(request):
                return JsonResponse({"ok": True, "preview_url": _draft_preview_url(profile)})
            if request.POST.get("next") == "publish":
                return redirect("themes:publish")
            messages.success(request, _("Brouillon enregistré ✓"))
            return redirect("themes:customize")
        draft = {**draft, **{k: v for k, v in data.items() if k != "palette"}}
    palette = services.clean_palette(draft.get("palette"), base=services.clean_palette(theme.palette))
    resolved = services.resolve(profile, "draft") if services.settings_for(profile) else None
    sections = services.normalize_sections(draft.get("sections"))
    context = {
        "theme": theme,
        "draft": draft,
        "error": error,
        "palette": palette,
        "palette_fields": [(key, palette[key]) for key in services.PALETTE_KEYS],
        "presets": [
            {"index": str(i), "palette": services.clean_palette(p), "name": p.get("name", "")}
            for i, p in enumerate(theme.palette_presets or [])
        ],
        "preset": forms.preset_index(theme, palette),
        "fonts": [(code, str(f["label"])) for code, f in services.FONT_PAIRS.items()],
        "corners": [(code, str(c["label"])) for code, c in services.CORNERS.items()],
        "layouts": Theme.Layout.choices,
        "sections": [
            {
                "key": s["key"],
                "label": services.section_label(s["key"], theme.category),
                "visible": s["visible"],
                "locked": s["key"] in services.LOCKED_SECTIONS,
                "first": i == 0,
                "last": i == len(sections) - 1,
            }
            for i, s in enumerate(sections)
        ],
        "preview_url": _draft_preview_url(profile) if resolved else reverse("themes:draft_preview"),
        "cta_max": services.CTA_MAX,
    }
    return _embeds_preview(dash_render(request, "themes/customize.html", context, status=400 if error else 200))


@require_safe
@profile_required
def draft_preview(request):
    resolved = services.resolve(request.profile, "draft")
    css_url = reverse("themes:draft_css") + f"?v={resolved.version}"
    response = render_profile_page(
        request, request.profile, owner_private=False, theme=resolved, stylesheet_url=css_url, preview=True
    )
    return _frameable(response)


@require_safe
@profile_required
def draft_css(request):
    return _frameable(theme_css_response(services.resolve(request.profile, "draft").css()))


# --- publication ------------------------------------------------------------------------------


PUBLISH_RATE = "10/h"


@require_http_methods(["GET", "HEAD", "POST"])
@profile_required
@ratelimit(key="user", rate=PUBLISH_RATE, method="POST", block=False, group="themes.publish")
def publish(request):
    profile = request.profile
    if not services.themes_enabled():
        return _back_to_gallery(request, _("Le choix des modèles est momentanément indisponible."))
    draft = services.current_draft(profile)
    theme = services.get_theme(draft.get("theme")) or services.default_theme()
    if request.method == "POST":
        if getattr(request, "limited", False):
            messages.error(request, _("Tu as déjà publié beaucoup de fois cette heure-ci. Réessaie un peu plus tard."))
            return redirect("themes:publish")
        try:
            services.publish(profile)
        except (ValidationError, services.ThemeError) as exc:
            message = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
            messages.error(request, message)
            return redirect("themes:publish")
        return redirect("themes:published")
    context = {
        "theme": theme,
        "locked": theme.is_premium and not services.has_premium(profile),
        "readiness": services.seo_readiness(profile),
        "preview_url": _draft_preview_url(profile) if services.settings_for(profile) else "",
    }
    return _embeds_preview(dash_render(request, "themes/publish.html", context))


def _status_context(profile) -> dict:
    pt = services.settings_for(profile)
    since = pt.published_at if pt else None
    status = services.notification_status(profile, since)
    return {"status": status, "published_at": since}


@require_safe
@profile_required
def published(request):
    profile = request.profile
    pt = services.settings_for(profile)
    if pt is None or not pt.published_at:
        return redirect("themes:gallery")
    profile.refresh_from_db()
    url = profile.absolute_url
    share_text = _("Découvre ma nouvelle page : %(url)s") % {"url": url}
    context = {
        "live_url": url,
        "theme": pt.theme,
        "version": pt.published_version,
        "indexable": profile.is_indexable,
        "blockers": [] if profile.is_indexable else services.seo_readiness(profile)["blockers"],
        "whatsapp_share": "https://wa.me/?text=" + quote(share_text),
        "facebook_share": "https://www.facebook.com/sharer/sharer.php?u=" + quote(url, safe=""),
        "share_text": share_text,
        **_status_context(profile),
    }
    return dash_render(request, "themes/published.html", context)


@require_safe
@profile_required
def published_status(request):
    """HTMX fragment polled by the success screen until the notification is final."""
    profile = request.profile
    profile.refresh_from_db()
    response = dash_render(request, "themes/partials/status.html", _status_context(profile))
    return set_private_no_store(response)
