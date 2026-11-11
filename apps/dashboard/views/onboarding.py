"""Five short onboarding steps. Each step saves immediately; steps 3 to 5 can be skipped.

Writes go through `apps.profiles.services` only. A suspended page can be looked at, never changed.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_http_methods

from apps.accounts.services import OTPError
from apps.platform.services import feature
from apps.profiles import services as profiles
from apps.profiles.models import Profile

from ..content import bio_suggestions, service_examples
from ..forms import BioForm, ContactForm, IdentityForm, QuickServicesForm, TradeCityForm, profile_values
from ..services import MAX_SERVICES, SESSION_PROFILE_KEY, active_profile, whatsapp_share_url
from .common import SAFE_METHODS, is_suspended, suspended_response

STEPS = [
    ("nom", gettext_lazy("Ton nom")),
    ("metier", gettext_lazy("Ton métier")),
    ("contact", gettext_lazy("Tes contacts")),
    ("photo", gettext_lazy("Ta photo")),
    ("presentation", gettext_lazy("Ta présentation")),
]
STEP_SLUGS = [slug for slug, _label in STEPS]
FINISH = "fin"
SKIPPABLE_FROM = 2  # index: steps 3, 4 and 5


def _next(step: str) -> str:
    index = STEP_SLUGS.index(step)
    return STEP_SLUGS[index + 1] if index + 1 < len(STEP_SLUGS) else FINISH


def _go(step: str):
    return redirect("dashboard:onboarding", step=step)


@login_required
@require_http_methods(["GET", "POST"])
def onboarding(request, step: str):
    if step != FINISH and step not in STEP_SLUGS:
        raise Http404
    profile = active_profile(request)
    if is_suspended(profile) and (request.method not in SAFE_METHODS or step == FINISH):
        return suspended_response(request, profile)  # never a second page, never a change
    if profile is None and step != "nom":
        return _go("nom")
    needs_trade = step in [*STEP_SLUGS[SKIPPABLE_FROM:], FINISH]
    if needs_trade and not ((profile.trade_id or profile.custom_title) and profile.city_id):
        return _go("metier")  # steps 1 and 2 are the minimum for a useful page
    if step == FINISH:
        return _finish(request, profile)

    skipping = request.method == "POST" and request.POST.get("action") in ("skip", "later")
    if skipping and STEP_SLUGS.index(step) >= SKIPPABLE_FROM:
        return _go(FINISH if request.POST["action"] == "later" else _next(step))

    handler = {
        "nom": _step_name,
        "metier": _step_trade,
        "contact": _step_contact,
        "photo": _step_photo,
        "presentation": _step_bio,
    }[step]
    result = handler(request, profile)
    if not isinstance(result, dict):
        return result  # a redirect: the step was saved
    index = STEP_SLUGS.index(step)
    context = {
        "step": step,
        "step_number": index + 1,
        "step_total": len(STEPS),
        "steps": [
            {"slug": s, "label": label, "done": i < index, "current": i == index} for i, (s, label) in enumerate(STEPS)
        ],
        "previous": STEP_SLUGS[index - 1] if index else "",
        "skippable": index >= SKIPPABLE_FROM,
        "profile": profile,
        **result,
    }
    return render(request, f"dashboard/onboarding/step_{step}.html", context)


def _step_name(request, profile: Profile | None):
    form = IdentityForm(request.POST or None, instance=profile)
    if profile is None and not feature("page_creation"):  # switch of the admin control center
        closed = _("La création de nouvelles pages est momentanément suspendue. Réessaie un peu plus tard.")
        if form.is_bound:
            form.add_error(None, closed)
        else:
            messages.warning(request, closed)
        return {"form": form, "creation_closed": True}
    if request.method == "POST" and form.is_valid():
        name, kind = form.cleaned_data["display_name"], form.cleaned_data["kind"]
        if profile is None:
            # Single entry point for page creation: never a duplicate for the same phone.
            try:
                _user, profile, created = profiles.get_or_create_profile(request.user.phone, name, kind=kind)
            except OTPError as exc:  # AccountNotAllowed: disabled or staff account
                form.add_error(None, str(exc))
                return {"form": form}
            if is_suspended(profile):
                return suspended_response(request, profile)
            if not created:
                profiles.update_profile(profile, display_name=name, kind=kind)
        else:
            profiles.update_profile(profile, **profile_values(form))
        request.session[SESSION_PROFILE_KEY] = profile.pk
        return _go(_next("nom"))
    if profile is None and not form.is_bound and request.user.full_name:
        form.initial["display_name"] = request.user.full_name
    return {"form": form}


def _step_trade(request, profile: Profile):
    form = TradeCityForm(request.POST or None, instance=profile, show_area=False)
    if request.method == "POST" and form.is_valid():
        profiles.update_profile(profile, **profile_values(form))
        return _go(_next("metier"))
    return {"form": form}


def _step_contact(request, profile: Profile):
    form = ContactForm(request.POST or None, instance=profile, short=True)
    if request.method == "POST" and form.is_valid():
        profiles.update_profile(profile, **profile_values(form))
        return _go(_next("contact"))
    return {"form": form}


def _step_photo(request, profile: Profile):
    error = ""
    if request.method == "POST":
        uploaded = next((f for f in request.FILES.getlist("photo") if f), None)
        if uploaded is None:
            error = _("Choisis une photo, ou appuie sur « Passer ».")
        else:
            try:
                profiles.set_photo(profile, uploaded)
            except ValidationError as exc:
                error = exc.messages[0]
            else:
                return _go(_next("photo"))
    return {"error": error}


def _step_bio(request, profile: Profile):
    form = BioForm(request.POST or None, instance=profile)
    services_form = QuickServicesForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and services_form.is_valid():
        profiles.update_profile(profile, **profile_values(form))
        for title, price in services_form.items():
            if profile.services.count() >= MAX_SERVICES:
                break
            try:
                profiles.add_service(profile, title, price_label=price)
            except ValidationError:
                break
        return _go(FINISH)
    return {
        "form": form,
        "services_form": services_form,
        "suggestions": bio_suggestions(profile),
        "service_examples": service_examples(profile),
        "existing_services": list(profile.services.all()[:5]),
    }


def _finish(request, profile: Profile):
    profiles.mark_onboarding_completed(profile)
    profiles.refresh_seo_state(profile, content_changed=False)
    items = profiles.completeness_items(profile)
    return render(
        request,
        "dashboard/onboarding/finish.html",
        {
            "profile": profile,
            "items": items,
            "todo": [i for i in items if not i["done"]],
            "whatsapp_share": whatsapp_share_url(profile),
        },
    )
