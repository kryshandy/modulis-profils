"""Card scan (/c/<code>) and activation wizard (/c/<code>/activer).

Rules: /c/ always answers 302 (never 301) with no-store + noindex (ADR-0003); the activation code is
checked BEFORE any SMS is sent (ADR-0005). With ATOMIC_REQUESTS, OTPError/CardError are always
caught and turned into form errors so the attempt counters are committed.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django_ratelimit.core import is_ratelimited
from django_ratelimit.decorators import ratelimit

from apps.accounts import services as accounts
from apps.accounts.models import OTPChallenge, User
from apps.analytics import services as analytics
from apps.analytics.models import Event
from apps.billing import services as billing
from apps.core.utils import client_ip, hash_ip, ratelimit_ip_key
from apps.profiles import services as profiles
from apps.profiles.models import Profile

from . import forms, services
from .models import Card

SCAN_RATE = "60/m"
UNKNOWN_CODE_RATE = "20/10m"  # an IP probing many unknown codes is blocked for a while
ACTIVATION_POST_RATE = "20/m"
STATE_TTL_SECONDS = 30 * 60
STEPS = ("code", "phone", "otp", "profile")


def _protect(response):
    """Every /c/ response: never cached, never indexed."""
    add_never_cache_headers(response)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _page(request, template: str, context: dict | None = None, status: int = 200):
    return _protect(render(request, template, context or {}, status=status))


def _redirect(url: str):
    return _protect(HttpResponseRedirect(url))


def _ip_hash(request) -> str:
    # Stable (non daily) hash: these counters protect hourly limits and must not reset at midnight.
    return hash_ip(client_ip(request), daily=False)


def _unknown_code_blocked(request, *, increment: bool) -> bool:
    return is_ratelimited(
        request, group="cards.unknown", key=ratelimit_ip_key, rate=UNKNOWN_CODE_RATE, increment=increment
    )


def _rate_limited(request):
    return _page(request, "cards/rate_limited.html", status=429)


# --- Scan ------------------------------------------------------------------------------------


@ratelimit(key=ratelimit_ip_key, rate=SCAN_RATE, block=False, group="cards.scan")
def scan(request, code: str):
    if getattr(request, "limited", False) or _unknown_code_blocked(request, increment=False):
        return _rate_limited(request)
    card = services.get_card(code)
    if card is None:
        _unknown_code_blocked(request, increment=True)
        return _page(request, "cards/unknown.html", {"code": code[:12]}, status=404)

    if card.status in (Card.Status.STOCK, Card.Status.SOLD):
        return _redirect(reverse("cards:activate", args=[card.public_code]))

    profile = card.profile
    if card.status == Card.Status.DISABLED:
        public_profile = profile if profile and profile.is_publicly_visible else None
        return _page(request, "cards/disabled.html", {"card": card, "profile": public_profile})

    # Active card.
    if profile is None or profile.status != Profile.Status.ACTIVE:
        return _page(request, "cards/unavailable.html", status=404)
    services.record_scan(card)
    analytics.record_event(profile, Event.Kind.SCAN, request, card=card)
    if profile.visibility == Profile.Visibility.PRIVATE:
        # The holder handed the card on purpose: show a minimal contact page, not indexed.
        return _page(request, "cards/contact.html", {"profile": profile})
    return _redirect(profile.get_absolute_url())


# --- Activation wizard -----------------------------------------------------------------------


def _state_key(card: Card) -> str:
    return f"card_activation:{card.public_code}"


def _get_state(request, card: Card) -> dict:
    state = request.session.get(_state_key(card))
    if not state or state.get("step") not in STEPS or time.time() - state.get("started", 0) > STATE_TTL_SECONDS:
        state = {"step": "code", "started": time.time()}
    return state


def _save_state(request, card: Card, state: dict) -> None:
    request.session[_state_key(card)] = state


def _clear_state(request, card: Card) -> None:
    request.session.pop(_state_key(card), None)


def _onboarding_url() -> str:
    try:
        return reverse("dashboard:onboarding")
    except NoReverseMatch:
        return "/espace/"


def _existing_profiles(phone: str) -> list[Profile]:
    user = User.objects.filter(phone=phone).first()
    if user is None:
        return []
    return list(user.profiles.exclude(status=Profile.Status.DELETED).select_related("trade", "city"))


def _may_create_another(profiles_list: list[Profile]) -> bool:
    if not profiles_list:
        return True
    allowed = max(int(billing.entitlements(p).get("max_profiles", 1) or 1) for p in profiles_list)
    return len(profiles_list) < allowed


@ratelimit(key=ratelimit_ip_key, rate=SCAN_RATE, block=False, group="cards.scan")
@ratelimit(key=ratelimit_ip_key, rate=ACTIVATION_POST_RATE, method="POST", block=False, group="cards.activate")
def activate(request, code: str):
    if getattr(request, "limited", False) or _unknown_code_blocked(request, increment=False):
        return _rate_limited(request)
    card = services.get_card(code)
    if card is None:
        _unknown_code_blocked(request, increment=True)
        return _page(request, "cards/unknown.html", {"code": code[:12]}, status=404)
    if card.status not in (Card.Status.STOCK, Card.Status.SOLD):
        _clear_state(request, card)
        return _redirect(reverse("cards:scan", args=[card.public_code]))

    state = _get_state(request, card)
    if request.method == "POST" and request.POST.get("action") == "restart":
        state = {"step": "code", "started": time.time()}
        _save_state(request, card, state)
        return _redirect(request.path)

    handler = {"code": _step_code, "phone": _step_phone, "otp": _step_otp, "profile": _step_profile}[state["step"]]
    return handler(request, card, state)


def _render_step(request, card: Card, state: dict, form, **extra):
    context = {
        "card": card,
        "step": state["step"],
        "step_number": STEPS.index(state["step"]) + 1,
        "step_count": len(STEPS),
        "form": form,
        "turnstile_site_key": settings.TURNSTILE_SITE_KEY if state["step"] == "code" else "",
        "phone_display": accounts.display_phone(state["phone"]) if state.get("phone") else "",
        **extra,
    }
    return _page(request, "cards/activate.html", context)


def _step_code(request, card: Card, state: dict):
    form = forms.ActivationCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not services.verify_turnstile(request.POST.get("cf-turnstile-response", ""), client_ip(request)):
            form.add_error(None, _("La vérification anti-robot a échoué. Réessaie."))
            return _render_step(request, card, state, form)
        ip_hash = _ip_hash(request)
        try:
            ok = services.check_activation_code(card, form.cleaned_data["activation_code"], ip_hash)
        except services.CardError as exc:
            form.add_error(None, str(exc))
            return _render_step(request, card, state, form)
        if not ok:
            left = services.activation_attempts_left(card, ip_hash)
            form.add_error(
                "activation_code",
                _("Code d'activation incorrect. Il te reste %(n)d essai(s) cette heure-ci.") % {"n": left},
            )
            return _render_step(request, card, state, form)
        state.update(step="phone", code_ok=True)
        _save_state(request, card, state)
        return _redirect(request.path)
    return _render_step(request, card, state, form)


def _step_phone(request, card: Card, state: dict):
    form = forms.PhoneForm(request.POST or None)
    if not state.get("code_ok"):  # defensive: never send an SMS before the activation code is verified
        return _redirect(request.path)
    if request.method == "POST" and form.is_valid():
        try:
            phone = accounts.normalize_phone(form.cleaned_data["phone"])
            accounts.request_otp(phone, OTPChallenge.Purpose.CARD_ACTIVATION, ip_hash=_ip_hash(request))
        except accounts.OTPError as exc:
            form.add_error("phone", str(exc))
            return _render_step(request, card, state, form)
        state.update(step="otp", phone=phone)
        _save_state(request, card, state)
        return _redirect(request.path)
    return _render_step(request, card, state, form)


def _step_otp(request, card: Card, state: dict):
    phone = state.get("phone")
    if not (state.get("code_ok") and phone):
        state.update(step="code")
        _save_state(request, card, state)
        return _redirect(request.path)
    if request.method == "POST" and request.POST.get("action") == "resend":
        form = forms.OTPForm()
        try:
            accounts.request_otp(phone, OTPChallenge.Purpose.CARD_ACTIVATION, ip_hash=_ip_hash(request))
            notice = _("Un nouveau code vient d'être envoyé.")
        except accounts.OTPError as exc:
            notice = str(exc)
        return _render_step(request, card, state, form, notice=notice)
    if request.method == "POST" and request.POST.get("action") == "change_phone":
        state.update(step="phone")
        state.pop("phone", None)
        _save_state(request, card, state)
        return _redirect(request.path)

    form = forms.OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            accounts.verify_otp(phone, OTPChallenge.Purpose.CARD_ACTIVATION, form.cleaned_data["code"])
        except accounts.OTPError as exc:
            form.add_error("code", str(exc))
            return _render_step(request, card, state, form)
        state.update(step="profile", verified=True)
        _save_state(request, card, state)
        return _redirect(request.path)
    return _render_step(request, card, state, form)


def _step_profile(request, card: Card, state: dict):
    phone = state.get("phone")
    if not (state.get("code_ok") and state.get("verified") and phone):
        state = {"step": "code", "started": time.time()}
        _save_state(request, card, state)
        return _redirect(request.path)
    user = User.objects.filter(phone=phone).first()
    if user is not None and not user.is_active:
        _clear_state(request, card)
        return _page(request, "cards/unavailable.html", {"account_disabled": True}, status=403)

    existing = _existing_profiles(phone)
    allow_new = _may_create_another(existing)
    action = request.POST.get("action") if request.method == "POST" else None

    if existing and action != "create":
        form = forms.ChooseProfileForm(
            request.POST if action == "choose" else None, profiles=existing, allow_new=allow_new
        )
        if action == "choose" and form.is_valid():
            profile = form.selected_profile()
            if profile is None:  # "create a new page" was chosen
                return _render_step(request, card, state, forms.NewProfileForm(), creating=True)
            user, _created = accounts.get_or_create_user(phone)  # marks the phone verified, updates last_seen
            return _finish(request, card, user, profile)
        return _render_step(request, card, state, form, creating=False)

    if not allow_new:
        return _redirect(request.path)
    form = forms.NewProfileForm(request.POST if action == "create" else None)
    if action == "create" and form.is_valid():
        data = form.cleaned_data
        if existing:  # another page for an account whose plan allows several
            user, _created = accounts.get_or_create_user(phone)
            profile = profiles.create_profile(user, data["display_name"], trade=data["trade"], city=data["city"])
        else:  # single entry point for automatic page creation (plan §5.1, entry B)
            user, profile, _created = profiles.get_or_create_profile(
                phone, data["display_name"], trade=data["trade"], city=data["city"]
            )
        return _finish(request, card, user, profile)
    return _render_step(request, card, state, form, creating=True)


def _finish(request, card: Card, user, profile: Profile):
    try:
        services.activate_card(card, profile)
    except services.CardError as exc:
        _clear_state(request, card)
        return _page(request, "cards/activate_failed.html", {"card": card, "error": str(exc)}, status=409)
    _clear_state(request, card)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")  # rotates the session key
    request.session["activated_card"] = card.public_code
    return _redirect(_onboarding_url())
