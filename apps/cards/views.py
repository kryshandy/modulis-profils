"""Card scan (/c/<code>) and activation wizard (/c/<code>/activer).

Rules: /c/ always answers 302 (never 301) with no-store + noindex (ADR-0003); the activation code is
checked BEFORE any SMS is sent (ADR-0005). With ATOMIC_REQUESTS, OTPError/CardError are always
caught and turned into form errors so the attempt counters are committed.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import login
from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django_ratelimit.core import is_ratelimited
from django_ratelimit.decorators import ratelimit

from apps.accounts import otp
from apps.accounts import services as accounts
from apps.accounts.models import OTPChallenge, User
from apps.analytics import services as analytics
from apps.analytics.models import Event
from apps.billing import services as billing
from apps.core import csp
from apps.core.turnstile import verify_turnstile
from apps.core.utils import client_ip, ratelimit_ip_key, security_ip_hash
from apps.legal.services import record_acceptance
from apps.platform.services import feature
from apps.profiles import services as profiles
from apps.profiles.models import Profile

from . import forms, services
from .models import Card

SCAN_RATE = "60/m"
UNKNOWN_CODE_RATE = "20/10m"  # an IP probing many unknown codes is blocked for a while
ACTIVATION_POST_RATE = "20/m"
STATE_TTL_SECONDS = 30 * 60
RESEND_DELAY = 60  # seconds between two SMS codes, as on the dashboard login
STEPS = ("code", "phone", "otp", "profile")
SESSION_PROFILE_KEY = "dashboard_profile_id"  # == apps.dashboard.services.SESSION_PROFILE_KEY


def _protect(response):
    """Every /c/ response: never cached, never indexed."""
    add_never_cache_headers(response)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _page(request, template: str, context: dict | None = None, status: int = 200):
    return _protect(render(request, template, context or {}, status=status))


def _redirect(url: str):
    return _protect(HttpResponseRedirect(url))


def _unknown_code_blocked(request, *, increment: bool) -> bool:
    return is_ratelimited(
        request, group="cards.unknown", key=ratelimit_ip_key, rate=UNKNOWN_CODE_RATE, increment=increment
    )


def _rate_limited(request):
    return _page(request, "cards/rate_limited.html", status=429)


def _activation_closed(request):
    """Switch of the admin control center: activations paused (active cards keep working)."""
    return _page(request, "cards/activation_closed.html", status=503)


PAGE_CREATION_CLOSED = gettext_lazy(
    "La création de nouvelles pages est momentanément suspendue : cette carte ne peut être liée "
    "qu'à une page existante. Réessaie un peu plus tard."
)


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
        if not feature("card_activation"):
            return _activation_closed(request)
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


def _resend_wait(state: dict) -> int:
    return max(0, RESEND_DELAY - int(time.time() - state.get("sent_at", 0)))


def _live_profiles(user: User | None) -> list[Profile]:
    if user is None:
        return []
    return list(user.profiles.exclude(status=Profile.Status.DELETED).select_related("trade", "city"))


def _may_create_another(profiles_list: list[Profile], *, total: int | None = None) -> bool:
    """`total` counts every live page of the account, suspended ones included (no ban evasion)."""
    count = len(profiles_list) if total is None else total
    if not count:
        return True
    if not profiles_list:
        return False
    allowed = max(int(billing.entitlements(p).get("max_profiles", 1) or 1) for p in profiles_list)
    return count < allowed


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
    if not feature("card_activation"):
        return _activation_closed(request)

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
        "resend_wait": _resend_wait(state) if state["step"] == "otp" else 0,
        **extra,
    }
    if state["step"] == "phone" and hasattr(form, "channel_options"):
        context["channel_options"] = form.channel_options()
    if state["step"] == "otp":
        channel = otp.get_channel(state.get("channel")) or otp.default_channel()
        if channel is not None and "code" in getattr(form, "fields", {}):
            form.fields["code"].label = channel.code_label
        context.update(
            channel=channel,
            other_channels=[c for c in otp.available_channels() if channel is None or c.code != channel.code],
            delivery_error=accounts.delivery_failure(state["phone"], OTPChallenge.Purpose.CARD_ACTIVATION),
        )
        if channel is not None and channel.kind == otp.CLIENT:
            autostart = bool(state.pop("autostart", False))
            _save_state(request, card, state)
            context["firebase"] = {
                **otp.CHANNELS[channel.code].web_config(),
                "sdk_version": settings.FIREBASE_SDK_VERSION,
                "phone": state["phone"],
                "verify_url": request.path,
                "autostart": autostart,
            }
    response = _page(request, "cards/activate.html", context)
    if context["turnstile_site_key"]:
        csp.allow(response, csp.TURNSTILE)
    if context.get("firebase"):
        csp.allow(response, csp.FIREBASE)
    return response


def _send_card_code(request, card: Card, state: dict, phone: str, channel: str | None) -> None:
    """Raises OTPError. Same rules as the dashboard login, for every channel."""
    challenge = accounts.request_otp(
        phone, OTPChallenge.Purpose.CARD_ACTIVATION, ip_hash=security_ip_hash(request), channel=channel
    )
    selected = otp.get_channel(challenge.channel)
    state.update(
        step="otp",
        phone=phone,
        sent_at=time.time(),
        channel=challenge.channel,
        autostart=bool(selected and selected.kind == otp.CLIENT),
    )
    _save_state(request, card, state)


def _json(data: dict, status: int = 200):
    return _protect(JsonResponse(data, status=status))


def _failed(request, card: Card, error: str, status: int):
    _clear_state(request, card)
    return _page(request, "cards/activate_failed.html", {"card": card, "error": error}, status=status)


def _step_code(request, card: Card, state: dict):
    form = forms.ActivationCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not verify_turnstile(request.POST.get("cf-turnstile-response", ""), client_ip(request)):
            form.add_error(None, _("La vérification anti-robot a échoué. Réessaie."))
            return _render_step(request, card, state, form)
        ip_hash = security_ip_hash(request)
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
    form = forms.PhoneForm(request.POST or None, channels=otp.available_channels())
    if not state.get("code_ok"):  # defensive: never send a code before the activation code is verified
        return _redirect(request.path)
    if request.method == "POST" and form.is_valid():
        try:
            phone = accounts.normalize_phone(form.cleaned_data["phone"])
            # Page creation switched off: we do NOT say here whether this number has a page (that
            # would reveal accounts to anyone holding a card). _step_profile refuses after the OTP.
            _send_card_code(request, card, state, phone, form.cleaned_data.get("channel") or None)
        except accounts.OTPError as exc:
            form.add_error("phone", str(exc))
            return _render_step(request, card, state, form)
        return _redirect(request.path)
    return _render_step(request, card, state, form)


def _step_otp(request, card: Card, state: dict):
    phone = state.get("phone")
    if not (state.get("code_ok") and phone):
        state.update(step="code")
        _save_state(request, card, state)
        return _redirect(request.path)
    action = request.POST.get("action") if request.method == "POST" else None
    channel = otp.get_channel(state.get("channel"))
    if action in ("resend", "switch"):
        form = forms.OTPForm()
        current = channel.code if channel else None
        target = request.POST.get("channel") if action == "switch" else current
        wait = _resend_wait(state) if target == current else 0
        if wait:
            notice = _("Patiente encore %(n)d secondes avant de redemander un code.") % {"n": wait}
            return _render_step(request, card, state, form, notice=notice)
        try:
            _send_card_code(request, card, state, phone, target or None)
        except accounts.OTPError as exc:
            notice = str(exc)
        else:
            notice = _("Un nouveau code a été demandé.")
        return _render_step(request, card, state, form, notice=notice)
    if action == "change_phone":
        state.update(step="phone")
        state.pop("phone", None)
        _save_state(request, card, state)
        return _redirect(request.path)
    if action == "firebase":
        # JSON endpoint of static/js/firebase-otp.js (CSRF header; rate-limited like every POST here).
        if channel is None or channel.kind != otp.CLIENT:
            return _json({"error": _("Ta session a expiré. Recommence l'activation.")}, status=400)
        try:
            accounts.verify_firebase_token(
                request.POST.get("id_token", ""), phone, OTPChallenge.Purpose.CARD_ACTIVATION
            )
        except accounts.OTPError as exc:
            return _json({"error": str(exc)}, status=400)
        state.update(step="profile", verified=True)
        _save_state(request, card, state)
        return _json({"redirect": request.path})

    form = forms.OTPForm(request.POST or None)
    if request.method == "POST" and channel is not None and channel.kind == otp.CLIENT:
        form.add_error(None, _("Active JavaScript pour valider ce code, ou choisis de recevoir le code par WhatsApp."))
        return _render_step(request, card, state, form)
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

    live = _live_profiles(user)
    existing = [p for p in live if p.status == Profile.Status.ACTIVE]
    if live and not existing:  # only suspended page(s): never a card, never a replacement page
        return _failed(
            request,
            card,
            _("Ta page est suspendue : tu ne peux pas y lier de carte. Contacte le support Modulis."),
            status=403,
        )
    creation_open = feature("page_creation")
    if not existing and not creation_open:  # switch of the admin control center
        return _failed(request, card, str(PAGE_CREATION_CLOSED), status=503)
    allow_new = creation_open and _may_create_another(existing, total=len(live))
    action = request.POST.get("action") if request.method == "POST" else None

    if existing and action != "create":
        form = forms.ChooseProfileForm(
            request.POST if action == "choose" else None, profiles=existing, allow_new=allow_new
        )
        if action == "choose" and form.is_valid():
            profile = form.selected_profile()
            if profile is None:  # "create a new page" was chosen
                return _render_step(request, card, state, forms.NewProfileForm(), creating=True)
            try:
                with transaction.atomic():
                    user, _created = accounts.get_or_create_user(phone)  # marks the phone verified
                    services.activate_card(card, profile)
            except accounts.OTPError as exc:  # AccountNotAllowed: staff or disabled account
                return _failed(request, card, str(exc), status=403)
            except services.CardError as exc:
                return _failed(request, card, str(exc), status=409)
            return _finish(request, card, user, profile)
        return _render_step(request, card, state, form, creating=False)

    if not allow_new:
        return _redirect(request.path)
    form = forms.NewProfileForm(request.POST if action == "create" else None)
    if action == "create" and form.is_valid():
        data = form.cleaned_data
        try:
            # One savepoint: if the card cannot be activated, the new page is rolled back too.
            with transaction.atomic():
                if existing:  # another page for an account whose plan allows several
                    user, _created = accounts.get_or_create_user(phone)
                    profile = profiles.create_profile(
                        user, data["display_name"], trade=data["trade"], city=data["city"]
                    )
                else:  # single entry point for automatic page creation (plan §5.1, entry B)
                    user, profile, _created = profiles.get_or_create_profile(
                        phone, data["display_name"], trade=data["trade"], city=data["city"]
                    )
                if profile.status != Profile.Status.ACTIVE:
                    raise services.CardError(_("Ta page est suspendue : tu ne peux pas y lier de carte."))
                services.activate_card(card, profile)
        except accounts.OTPError as exc:  # AccountNotAllowed: staff or disabled account
            return _failed(request, card, str(exc), status=403)
        except services.CardError as exc:
            return _failed(request, card, str(exc), status=409)
        return _finish(request, card, user, profile)
    return _render_step(request, card, state, form, creating=True)


def _finish(request, card: Card, user, profile: Profile):
    """Card activated: log in and continue in the pro space (onboarding if the page is new)."""
    _clear_state(request, card)
    if not user.terms_version:  # first acceptance: the phone step states that continuing accepts the CGU
        record_acceptance(user)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")  # rotates the session key
    request.session["activated_card"] = card.public_code
    request.session[SESSION_PROFILE_KEY] = profile.pk  # the dashboard opens on the page just linked
    if profile.onboarding_completed_at is None:
        return _redirect(reverse("dashboard:onboarding", kwargs={"step": "nom"}))
    return _redirect(reverse("dashboard:home"))
