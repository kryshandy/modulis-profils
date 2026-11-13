"""CGU, privacy policy, legal notice, and the acceptance screen of the pro space."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods

from .conf import LEGAL_CHANGES, LEGAL_EFFECTIVE_DATE, LEGAL_VERSION, company
from .services import needs_acceptance, record_acceptance


def _context(**extra) -> dict:
    return {"legal": company(), "legal_version": LEGAL_VERSION, "legal_date": LEGAL_EFFECTIVE_DATE, **extra}


@require_GET
def terms(request):
    return render(request, "legal/cgu.html", _context(doc="terms"))


@require_GET
def privacy(request):
    return render(request, "legal/confidentialite.html", _context(doc="privacy"))


@require_GET
def notice(request):
    return render(request, "legal/mentions_legales.html", _context(doc="notice"))


def _safe_next(request, value: str) -> str:
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=False):
        return value
    return "/espace/"


@login_required(login_url="dashboard:login")
@require_http_methods(["GET", "POST"])
def accept(request):
    nxt = _safe_next(request, request.POST.get("next") or request.GET.get("next", ""))
    if not needs_acceptance(request.user):
        return redirect(nxt)
    error = False
    if request.method == "POST":
        if request.POST.get("accept") == "1":
            record_acceptance(request.user)
            return redirect(nxt)
        error = True
    first_time = not request.user.terms_version
    context = _context(next=nxt, changes=LEGAL_CHANGES, first_time=first_time, error=error)
    return render(request, "legal/accept.html", context, status=400 if error else 200)
