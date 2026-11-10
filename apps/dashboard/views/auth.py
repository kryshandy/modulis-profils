"""SMS one-time-code login. No password, ever (ADR-0004).

ATOMIC_REQUESTS is on: service exceptions are always caught and rendered, never propagated, so
that the attempt counters written by the services are committed.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.accounts.services import OTPError, display_phone, get_or_create_user, normalize_phone, request_otp, verify_otp
from apps.core.turnstile import verify_turnstile
from apps.core.utils import client_ip, ratelimit_ip_key, security_ip_hash

from ..forms import CodeForm, PhoneForm
from ..services import SESSION_PROFILE_KEY, user_profiles

SESSION_PHONE = "otp_phone"
SESSION_SENT_AT = "otp_sent_at"
SESSION_NEXT = "login_next"
RESEND_DELAY = 60
TURNSTILE_FIELD = "cf-turnstile-response"


def _send_code(request, phone: str) -> None:
    request_otp(phone, "login", ip_hash=security_ip_hash(request))
    request.session[SESSION_PHONE] = phone
    request.session[SESSION_SENT_AT] = int(time.time())


def _resend_wait(request) -> int:
    sent_at = request.session.get(SESSION_SENT_AT) or 0
    return max(0, RESEND_DELAY - (int(time.time()) - int(sent_at)))


@require_http_methods(["GET", "POST"])
@ratelimit(key=ratelimit_ip_key, rate="20/h", method="POST", block=False)
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    nxt = request.GET.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=False):
        request.session[SESSION_NEXT] = nxt
    form = PhoneForm(request.POST or None)
    error = ""
    if request.method == "POST":
        if getattr(request, "limited", False):
            error = _("Trop de tentatives depuis cet appareil. Réessaie dans une heure.")
        elif not verify_turnstile(request.POST.get(TURNSTILE_FIELD, ""), client_ip(request)):
            error = _("La vérification anti-robot a échoué. Réessaie.")
        elif form.is_valid():
            try:
                phone = normalize_phone(form.cleaned_data["phone"])
                _send_code(request, phone)
            except OTPError as exc:
                error = str(exc)
            else:
                return redirect("dashboard:verify")
    context = {"form": form, "error": error, "turnstile_site_key": settings.TURNSTILE_SITE_KEY}
    return render(request, "dashboard/auth/login.html", context, status=200)


@require_http_methods(["GET", "POST"])
@ratelimit(key=ratelimit_ip_key, rate="30/h", method="POST", block=False)
def verify_view(request):
    phone = request.session.get(SESSION_PHONE)
    if not phone:
        return redirect("dashboard:login")
    form = CodeForm()
    error = ""
    if request.method == "POST" and request.POST.get("action") == "resend":
        wait = _resend_wait(request)
        if wait:
            error = _("Patiente encore %(n)d secondes avant de redemander un code.") % {"n": wait}
        else:
            try:
                _send_code(request, phone)
            except OTPError as exc:
                error = str(exc)
            else:
                messages.info(request, _("Nouveau code envoyé par SMS."))
                return redirect("dashboard:verify")
    elif request.method == "POST":
        form = CodeForm(request.POST)
        if getattr(request, "limited", False):
            error = _("Trop de tentatives depuis cet appareil. Réessaie dans une heure.")
        elif form.is_valid():
            try:
                verify_otp(phone, "login", form.cleaned_data["code"])
                return _complete_login(request, phone)
            except OTPError as exc:  # wrong code, or AccountNotAllowed (staff / disabled account)
                error = str(exc)
    context = {
        "form": form,
        "error": error,
        "phone_display": display_phone(phone),
        "resend_wait": _resend_wait(request),
        "code_length": settings.OTP_LENGTH,
    }
    return render(request, "dashboard/auth/verify.html", context)


def _complete_login(request, phone: str):
    """Log the verified phone in. Raises OTPError (AccountNotAllowed) for staff or disabled accounts."""
    user, _created = get_or_create_user(phone)
    if not user.is_active:  # get_or_create_user already refuses it: never rely on a single check
        raise OTPError(_("Ce compte ne peut pas se connecter par SMS. Contacte le support Modulis."))
    nxt = request.session.get(SESSION_NEXT, "")
    login(request, user)  # rotates the session key
    for key in (SESSION_PHONE, SESSION_SENT_AT, SESSION_NEXT, SESSION_PROFILE_KEY):
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
