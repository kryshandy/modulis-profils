"""Staff 2FA pages, mounted on the admin site under <ADMIN_URL>securite/2fa/ (see admin.py).

These views are NOT wrapped by admin.site.admin_view (it refuses unverified staff): each one checks
that the user is an active staff member itself. Pages extend "admin/base_site.html".
"""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import services
from .forms import EnrollForm, VerifyForm

LOW_BACKUP_CODES = 3


def _with_next(name: str, target: str) -> str:
    return f"{reverse(name)}?{urlencode({'next': target})}"


def staff_view(view):
    """Active staff only (verified or not); everything else goes to the admin login."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and user.is_active and user.is_staff):
            return redirect_to_login(request.get_full_path(), reverse("admin:login"))
        response = view(request, *args, **kwargs)
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response

    return never_cache(csrf_protect(wrapped))


def verified_staff_view(view):
    """Active staff whose session passed 2FA (or 2FA disabled in development)."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if services.needs_two_factor(request.user):
            return services.redirect_to_two_factor(request)
        return view(request, *args, **kwargs)

    return staff_view(wrapped)


def _context(request, **extra) -> dict:
    context = admin.site.each_context(request)
    verified = not services.needs_two_factor(request.user)
    if not verified:  # no menu, no model list before 2FA
        context.update(available_apps=[], is_nav_sidebar_enabled=False)
    context.update(extra)
    return context


def _locked(request):
    context = _context(request, title=_("Trop de tentatives"))
    response = TemplateResponse(request, "admin/security/locked.html", context, status=429)
    response["Retry-After"] = str(settings.STAFF_2FA_WINDOW_SECONDS)
    return response


@staff_view
def enroll(request):
    user = request.user
    if services.has_confirmed_device(user):
        return redirect(_with_next("admin:security_2fa_verify", services.safe_next(request)))
    device = services.pending_device(user)
    form = EnrollForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not services.register_attempt(request):
            return _locked(request)
        codes = services.confirm_enrollment(request, device, form.cleaned_data["code"])
        if codes:
            services.stash_backup_codes(request, codes)
            messages.success(request, _("Double authentification activée."))
            return redirect(_with_next("admin:security_2fa_backup_codes", services.safe_next(request)))
        form.add_error("code", _("Code incorrect ou expiré. Vérifie l'heure de ton téléphone et réessaie."))
    context = _context(
        request,
        title=_("Activer la double authentification"),
        form=form,
        qr_svg=services.qr_svg(device),
        secret=services.manual_secret(device),
        issuer=settings.OTP_TOTP_ISSUER,
        account=user.phone,
        next=services.safe_next(request),
    )
    return TemplateResponse(request, "admin/security/enroll.html", context)


@staff_view
def verify(request):
    user = request.user
    target = services.safe_next(request)
    if not services.needs_two_factor(user):
        return redirect(target)
    if not services.has_confirmed_device(user):
        return services.redirect_to_two_factor(request)
    form = VerifyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        result = services.verify(request, form.cleaned_data["code"])
        if result == services.LOCKED:
            return _locked(request)
        if result in (services.OK, services.OK_BACKUP):
            if result == services.OK_BACKUP:
                left = services.remaining_backup_codes(user)
                level = messages.WARNING if left <= LOW_BACKUP_CODES else messages.INFO
                messages.add_message(
                    request,
                    level,
                    _("Code de secours utilisé. Il t'en reste %(n)d : régénère-les si besoin.") % {"n": left},
                )
            return redirect(target)
        form.add_error("code", _("Code incorrect. Réessaie avec un nouveau code de l'application."))
    context = _context(request, title=_("Vérification en deux étapes"), form=form, next=target)
    return TemplateResponse(request, "admin/security/verify.html", context)


@verified_staff_view
def backup_codes(request):
    if request.method == "POST":
        services.forget_backup_codes(request)
        return redirect(services.safe_next(request))
    codes = services.stashed_backup_codes(request)
    context = _context(
        request,
        title=_("Codes de secours"),
        codes=[services.format_backup_code(c) for c in codes],
        next=services.safe_next(request),
    )
    return TemplateResponse(request, "admin/security/backup_codes.html", context)


@verified_staff_view
def backup_codes_download(request):
    codes = services.stashed_backup_codes(request)
    if not codes:
        raise Http404
    lines = [
        _("Modulis Profils — codes de secours de la double authentification"),
        _("Compte : %(phone)s — générés le %(date)s")
        % {"phone": request.user.phone, "date": timezone.localtime().strftime("%d/%m/%Y %H:%M")},
        _("Chaque code ne fonctionne qu'une seule fois. Garde ce fichier en lieu sûr (pas sur ton téléphone)."),
        "",
        *(services.format_backup_code(c) for c in codes),
        "",
    ]
    response = HttpResponse("\r\n".join(lines), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="modulis-codes-de-secours.txt"'
    response["Cache-Control"] = "no-store"
    return response


@verified_staff_view
@require_POST
def backup_codes_regenerate(request):
    codes = services.regenerate_backup_codes_for_session(request)
    services.stash_backup_codes(request, codes)
    messages.success(request, _("Nouveaux codes de secours générés : les anciens ne fonctionnent plus."))
    return redirect("admin:security_2fa_backup_codes")


@verified_staff_view
def overview(request):
    user = request.user
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    context = _context(
        request,
        title=_("Double authentification"),
        device=device,
        backup_left=services.remaining_backup_codes(user),
        required=settings.STAFF_2FA_REQUIRED,
    )
    return TemplateResponse(request, "admin/security/overview.html", context)
