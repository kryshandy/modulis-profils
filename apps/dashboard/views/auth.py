"""One-time-code login by WhatsApp or SMS. No password, ever (ADR-0004, ADR-0009).

ATOMIC_REQUESTS is on: service exceptions are always caught and rendered, never propagated, so
that the attempt counters written by the services are committed.

Server channels (WhatsApp, SMS gateway, dev console): we send the code, the pro types it here.
Firebase SMS (client channel): our checks run first (login_view creates a pending challenge), then
static/js/firebase-otp.js sends and checks the SMS with Firebase and posts the ID token to
`firebase_verify_view`, which verifies it server side before logging in.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.accounts import otp
from apps.accounts.services import (
    OTPError,
    delivery_failure,
    display_phone,
    get_or_create_user,
    normalize_phone,
    request_otp,
    verify_firebase_token,
    verify_otp,
)
from apps.core.turnstile import verify_turnstile
from apps.core.utils import client_ip, ratelimit_ip_key, security_ip_hash
from apps.platform.services import feature

from ..forms import CodeForm, PhoneForm
from ..services import SESSION_PROFILE_KEY, user_profiles

SESSION_PHONE = "otp_phone"
SESSION_SENT_AT = "otp_sent_at"
SESSION_NEXT = "login_next"
SESSION_CHANNEL = "otp_channel"
SESSION_AUTOSTART = "otp_firebase_autostart"
RESEND_DELAY = 60
TURNSTILE_FIELD = "cf-turnstile-response"
PURPOSE = "login"


def _send_code(request, phone: str, channel: str | None) -> None:
    challenge = request_otp(phone, PURPOSE, ip_hash=security_ip_hash(request), channel=channel)
    request.session[SESSION_PHONE] = phone
    request.session[SESSION_SENT_AT] = int(time.time())
    request.session[SESSION_CHANNEL] = challenge.channel
    selected = otp.get_channel(challenge.channel)
    request.session[SESSION_AUTOSTART] = bool(selected and selected.kind == otp.CLIENT)


def _resend_wait(request) -> int:
    sent_at = request.session.get(SESSION_SENT_AT) or 0
    return max(0, RESEND_DELAY - (int(time.time()) - int(sent_at)))


def firebase_context(channel, *, phone: str, verify_url: str, autostart: bool) -> dict:
    """Template context for the Firebase browser flow (public config only, via data-* attributes)."""
    if channel is None or channel.kind != otp.CLIENT:
        return {}
    return {
        "firebase": {
            **otp.CHANNELS[channel.code].web_config(),
            "sdk_version": settings.FIREBASE_SDK_VERSION,
            "phone": phone,
            "verify_url": verify_url,
            "autostart": autostart,
        }
    }


@require_http_methods(["GET", "POST"])
@ratelimit(key=ratelimit_ip_key, rate="20/h", method="POST", block=False)
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    nxt = request.GET.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=False):
        request.session[SESSION_NEXT] = nxt
    channels = otp.available_channels()
    form = PhoneForm(request.POST or None, channels=channels)
    error = ""
    login_open = feature("login")
    if not login_open:
        error = _("La connexion est momentanément indisponible. Réessaie un peu plus tard.")
    elif not channels:
        error = _("L'envoi de codes est momentanément indisponible. Réessaie plus tard.")
    if request.method == "POST" and not error:
        if getattr(request, "limited", False):
            error = _("Trop de tentatives depuis cet appareil. Réessaie dans une heure.")
        elif not verify_turnstile(request.POST.get(TURNSTILE_FIELD, ""), client_ip(request)):
            error = _("La vérification anti-robot a échoué. Réessaie.")
        elif form.is_valid():
            try:
                phone = normalize_phone(form.cleaned_data["phone"])
                _send_code(request, phone, form.cleaned_data.get("channel") or None)
            except OTPError as exc:
                error = str(exc)
            else:
                return redirect("dashboard:verify")
    context = {
        "form": form,
        "error": error,
        "login_open": login_open and bool(channels),
        "channel_options": form.channel_options(),
        "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
    }
    return render(request, "dashboard/auth/login.html", context, status=200)


@require_http_methods(["GET", "POST"])
@ratelimit(key=ratelimit_ip_key, rate="30/h", method="POST", block=False)
def verify_view(request):
    phone = request.session.get(SESSION_PHONE)
    if not phone:
        return redirect("dashboard:login")
    channel = otp.get_channel(request.session.get(SESSION_CHANNEL)) or otp.default_channel()
    form = CodeForm()
    error = ""
    action = request.POST.get("action") if request.method == "POST" else None
    if action in ("resend", "switch"):
        current = channel.code if channel else None
        target = request.POST.get("channel") if action == "switch" else current
        # Switching to another channel (e.g. WhatsApp failed) skips the delay, never the hourly caps.
        wait = _resend_wait(request) if target == current else 0
        if wait:
            error = _("Patiente encore %(n)d secondes avant de redemander un code.") % {"n": wait}
        else:
            try:
                _send_code(request, phone, target or None)
            except OTPError as exc:
                error = str(exc)
            else:
                messages.info(request, _("Nouveau code demandé."))
                return redirect("dashboard:verify")
    elif request.method == "POST":
        form = CodeForm(request.POST)
        if getattr(request, "limited", False):
            error = _("Trop de tentatives depuis cet appareil. Réessaie dans une heure.")
        elif channel is not None and channel.kind == otp.CLIENT:
            error = _("Active JavaScript pour valider ce code, ou choisis de recevoir le code par WhatsApp.")
        elif form.is_valid():
            try:
                verify_otp(phone, PURPOSE, form.cleaned_data["code"])
                return _complete_login(request, phone)
            except OTPError as exc:  # wrong code, or AccountNotAllowed (staff / disabled account)
                error = str(exc)
    if channel is not None:
        form.fields["code"].label = channel.code_label
    autostart = bool(request.session.pop(SESSION_AUTOSTART, False))
    others = [c for c in otp.available_channels() if channel is None or c.code != channel.code]
    context = {
        "form": form,
        "error": error,
        "channel": channel,
        "other_channels": others,
        "delivery_error": delivery_failure(phone, PURPOSE),
        "phone_display": display_phone(phone),
        "resend_wait": _resend_wait(request),
        "code_length": settings.OTP_LENGTH,
        **firebase_context(channel, phone=phone, verify_url=reverse("dashboard:firebase_verify"), autostart=autostart),
    }
    return render(request, "dashboard/auth/verify.html", context)


@require_POST
@ratelimit(key=ratelimit_ip_key, rate="10/m", method="POST", block=False, group="auth.firebase")
@ratelimit(key=ratelimit_ip_key, rate="30/h", method="POST", block=False, group="auth.firebase.hour")
def firebase_verify_view(request):
    """Receive the Firebase ID token (CSRF-protected fetch) and log in. JSON in, JSON out."""
    phone = request.session.get(SESSION_PHONE)
    channel = otp.get_channel(request.session.get(SESSION_CHANNEL))
    if getattr(request, "limited", False):
        return JsonResponse(
            {"error": _("Trop de tentatives depuis cet appareil. Réessaie dans une heure.")}, status=429
        )
    if not phone or channel is None or channel.kind != otp.CLIENT:
        return JsonResponse({"error": _("Ta session a expiré. Recommence la connexion.")}, status=400)
    try:
        verify_firebase_token(request.POST.get("id_token", ""), phone, PURPOSE)
        response = _complete_login(request, phone)
    except OTPError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"redirect": response["Location"]})


def _complete_login(request, phone: str):
    """Log the verified phone in. Raises OTPError (AccountNotAllowed) for staff or disabled accounts."""
    user, _created = get_or_create_user(phone)
    if not user.is_active:  # get_or_create_user already refuses it: never rely on a single check
        raise OTPError(_("Ce compte ne peut pas se connecter avec un code. Contacte le support Modulis."))
    nxt = request.session.get(SESSION_NEXT, "")
    login(request, user)  # rotates the session key
    for key in (SESSION_PHONE, SESSION_SENT_AT, SESSION_NEXT, SESSION_PROFILE_KEY, SESSION_CHANNEL, SESSION_AUTOSTART):
        request.session.pop(key, None)
    if not user_profiles(user).exists():
        return redirect("dashboard:onboarding", step="nom")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=False):
        return redirect(nxt)
    return redirect("dashboard:home")


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, _("Tu es déconnecté. À bientôt !"))
    return redirect("dashboard:login")
