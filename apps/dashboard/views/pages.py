"""Home, share, cards, statistics, settings and help screens."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.accounts.services import set_email
from apps.cards.services import CardError, activate_card, check_activation_code, disable_card, get_card
from apps.core import csp
from apps.core.turnstile import verify_turnstile
from apps.core.utils import client_ip, ratelimit_ip_key, security_ip_hash
from apps.legal.export import export_user_data
from apps.platform.services import audit
from apps.profiles import services as profiles

from ..forms import DeleteProfileForm, LanguageForm, LinkCardForm, RecoveryEmailForm, SlugForm
from ..services import (
    SESSION_PROFILE_KEY,
    series_rows,
    set_active_profile,
    share_text,
    stat_rows,
    stats_30_days,
    whatsapp_share_url,
)
from .common import dash_render, profile_required, with_toast
from .editor import ITEM_SECTIONS

RING_RADIUS = 52
SITE_HOST = settings.SITE_URL.split("://", 1)[-1]
RING_CIRCUMFERENCE = 326.73  # 2 * pi * 52
TURNSTILE_FIELD = "cf-turnstile-response"


def gauge(score: int) -> dict:
    score = max(0, min(100, int(score or 0)))
    filled = round(RING_CIRCUMFERENCE * score / 100, 2)
    return {"score": score, "filled": filled, "rest": round(RING_CIRCUMFERENCE - filled, 2), "r": RING_RADIUS}


@profile_required
@require_GET
def home(request):
    profile = request.profile
    items = profiles.completeness_items(profile)
    for item in items:
        item["section"] = ITEM_SECTIONS.get(item["key"], "identite")
    stats = stats_30_days(profile)
    tour_auto = profile.tour_completed_at is None and profile.onboarding_completed_at is not None
    context = {
        "items": items,
        "todo_count": sum(1 for i in items if not i["done"]),
        "gauge": gauge(profile.completeness_score),
        "blockers": [] if profile.is_indexable else profiles.indexability_blockers(profile),
        "stats": stats,
        "whatsapp_share": whatsapp_share_url(profile),
        "tour_autostart": tour_auto or request.GET.get("visite") == "1",
        "onboarding_pending": profile.onboarding_completed_at is None,
    }
    return dash_render(request, "dashboard/home.html", context)


@profile_required
@require_POST
def tour_done(request):
    profiles.mark_tour_completed(request.profile)
    if request.htmx or request.headers.get("X-Requested-With") == "fetch":
        return HttpResponse(status=204)
    return redirect("dashboard:home")


@profile_required(allow_suspended=True)
@require_POST
def switch_profile(request):
    if not set_active_profile(request, request.POST.get("profile_id")):
        return HttpResponseBadRequest()
    messages.info(request, _("Tu gères maintenant une autre page."))
    return redirect("dashboard:home")


# --- Share ------------------------------------------------------------------------------------


@profile_required
@require_GET
def share(request):
    profile = request.profile
    return dash_render(
        request,
        "dashboard/share.html",
        {"share_text": share_text(profile), "whatsapp_share": whatsapp_share_url(profile)},
    )


@profile_required
@require_GET
def poster(request):
    return render(request, "dashboard/poster.html", {"profile": request.profile})


# --- Cards ------------------------------------------------------------------------------------


def _cards_context(request, form=None, error=""):
    return {
        "cards": list(request.profile.cards.order_by("-activated_at", "-created_at")),
        "form": form or LinkCardForm(),
        "error": error,
        "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
    }


def _cards_page(request, context):
    response = dash_render(request, "dashboard/cards.html", context, status=200)
    return csp.allow(response, csp.TURNSTILE) if context["turnstile_site_key"] else response


@profile_required
@require_GET
def cards(request):
    return _cards_page(request, _cards_context(request))


@profile_required
@require_POST
@ratelimit(key=ratelimit_ip_key, rate="10/h", method="POST", block=False)
def card_link(request):
    form = LinkCardForm(request.POST)
    error = ""
    if getattr(request, "limited", False):
        error = _("Trop d'essais depuis cet appareil. Réessaie dans une heure.")
    elif not verify_turnstile(request.POST.get(TURNSTILE_FIELD, ""), client_ip(request)):
        error = _("La vérification anti-robot a échoué. Réessaie.")
    elif form.is_valid():
        card = get_card(form.cleaned_data["public_code"])
        if card is None:
            error = _("Aucune carte ne porte ce code. Vérifie les 7 caractères au dos de la carte.")
        else:
            try:
                ok = check_activation_code(card, form.cleaned_data["activation_code"], security_ip_hash(request))
                if not ok:
                    error = _("Le code d'activation ne correspond pas. Vérifie-le sous la zone à gratter.")
                else:
                    activate_card(card, request.profile)
            except CardError as exc:
                error = str(exc)
    if not error and form.is_valid():
        messages.success(request, _("Ta carte est liée à ta page ✓ Fais un essai : approche-la d'un téléphone."))
        return redirect("dashboard:cards")
    return _cards_page(request, _cards_context(request, form, error))


@profile_required
@require_POST
def card_lost(request, pk: int):
    card = get_object_or_404(request.profile.cards, pk=pk)  # only cards of the user's own profile
    try:
        disable_card(card, "lost")
    except CardError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("Carte désactivée. Elle ne mène plus à ta page."))
    return redirect("dashboard:cards")


# --- Stats ------------------------------------------------------------------------------------


@profile_required
@require_GET
def stats(request):
    data = stats_30_days(request.profile)
    return dash_render(
        request,
        "dashboard/stats.html",
        {"stats": data, "rows": stat_rows(data), "daily": series_rows(data), "available": data is not None},
    )


# --- Settings ---------------------------------------------------------------------------------


def _settings_context(request, **forms):
    profile = request.profile
    return {
        "slug_form": forms.get("slug_form") or SlugForm(initial={"slug": profile.slug}),
        "language_form": forms.get("language_form") or LanguageForm(instance=profile),
        "email_form": forms.get("email_form") or RecoveryEmailForm(initial={"email": request.user.email}),
        "delete_form": forms.get("delete_form") or DeleteProfileForm(expected=profile.slug),
    }


def _saved(request, url_name: str = "dashboard:settings"):
    if request.htmx:
        return with_toast(HttpResponse(status=204))
    messages.success(request, _("Enregistré ✓"))
    return redirect(url_name)


@profile_required
def settings_view(request):
    profile = request.profile
    if request.method != "POST":
        return dash_render(request, "dashboard/settings.html", _settings_context(request))
    action = request.POST.get("action")
    if action == "slug":
        form = SlugForm(request.POST)
        if form.is_valid():
            try:
                profiles.change_slug(profile, form.cleaned_data["slug"])
            except ValidationError as exc:
                form.add_error("slug", exc.messages[0])
            else:
                messages.success(request, _("Ta nouvelle adresse est %(url)s ✓") % {"url": profile.absolute_url})
                return redirect("dashboard:settings")
        return dash_render(request, "dashboard/settings.html", _settings_context(request, slug_form=form))
    if action == "language":
        form = LanguageForm(request.POST, instance=profile)
        if form.is_valid():
            profiles.set_language(profile, form.cleaned_data["language"])
            return _saved(request)
        profile.refresh_from_db()
        return dash_render(request, "dashboard/settings.html", _settings_context(request, language_form=form))
    if action == "email":
        form = RecoveryEmailForm(request.POST)
        if form.is_valid():
            set_email(request.user, form.cleaned_data["email"])
            return _saved(request)
        return dash_render(request, "dashboard/settings.html", _settings_context(request, email_form=form))
    if action == "delete":
        form = DeleteProfileForm(request.POST, expected=profile.slug)
        if form.is_valid():
            profiles.delete_profile(profile)
            request.session.pop(SESSION_PROFILE_KEY, None)
            logout(request)
            messages.info(request, _("Ta page a été supprimée. Merci d'avoir utilisé Modulis Profils."))
            return redirect("dashboard:login")
        return dash_render(request, "dashboard/settings.html", _settings_context(request, delete_form=form))
    return HttpResponseBadRequest()


@profile_required
@require_GET
@ratelimit(key="user", rate="60/m", block=False)
def slug_check(request):
    """HTMX fragment: is this address free? Never reveals who owns a taken address."""
    profile = request.profile
    slug = (request.GET.get("slug") or "").strip().lower()
    state, message = "error", ""
    if getattr(request, "limited", False):
        message = _("Doucement ! Attends quelques secondes et réessaie.")
    elif not slug or slug == profile.slug:
        state, message = "neutral", _("C'est ton adresse actuelle.")
    else:
        try:
            profiles.validate_slug_format(slug)
        except ValidationError as exc:
            message = exc.messages[0]
        else:
            own_old = profile.slugs.filter(slug=slug, kind="old").exists()
            if own_old:
                state, message = "ok", _("C'est une de tes anciennes adresses : tu peux la reprendre.")
            elif not profiles.is_slug_available(slug):
                message = _("Cette adresse est déjà prise. Essaie d'ajouter ton quartier ou ton métier.")
            elif not profile.is_indexable and profiles.is_generic_slug(slug):
                message = _("Trop générique pour l'instant : ajoute ton prénom (ex. paul-plombier).")
            else:
                state, message = "ok", _("Libre ! Ta page serait : %(url)s") % {"url": f"{SITE_HOST}/{slug}"}
    return render(request, "dashboard/partials/slug_status.html", {"state": state, "message": message})


# --- Help -------------------------------------------------------------------------------------


@profile_required
@require_GET
def help_view(request):
    support = getattr(settings, "SUPPORT_WHATSAPP", "")
    return dash_render(request, "dashboard/help.html", {"support_whatsapp": support.lstrip("+")})


@login_required
@require_GET
@ratelimit(key="user", rate="10/h", block=False)
def data_export(request):
    """Right of access and portability: download everything about the account as JSON."""
    if getattr(request, "limited", False):
        messages.error(request, _("Tu as déjà téléchargé tes données plusieurs fois. Réessaie dans une heure."))
        return redirect("dashboard:settings")
    data = export_user_data(request.user)
    audit(request.user, "data_export", target=f"user:{request.user.pk}")
    response = JsonResponse(data, encoder=DjangoJSONEncoder, json_dumps_params={"ensure_ascii": False, "indent": 2})
    filename = f"modulis-mes-donnees-{timezone.localdate().isoformat()}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response
