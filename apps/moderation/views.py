from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit

from apps.core.utils import ratelimit_ip_key, security_ip_hash
from apps.platform.services import feature
from apps.profiles import services as profile_services
from apps.profiles.models import SlugRegistry

from . import services
from .forms import ReportForm


def _reportable_profile(slug: str):
    kind, profile = profile_services.resolve_slug(slug)
    if kind not in (SlugRegistry.Kind.CURRENT, SlugRegistry.Kind.OLD) or profile is None:
        raise Http404
    if not profile.is_publicly_visible:
        raise Http404
    return profile


def _noindex(response):
    add_never_cache_headers(response)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _reports_closed(request, profile):
    """Public reports switched off in the control center: friendly 200 page, never indexed."""
    context = {
        "title": _("Signalements momentanément fermés"),
        "message": _(
            "Le formulaire de signalement est momentanément indisponible. Réessaie plus tard ou contacte le support."
        ),
        "back_url": profile.get_absolute_url(),
    }
    return _noindex(render(request, "platform/feature_closed.html", context))


@ratelimit(key=ratelimit_ip_key, rate="5/h", method="POST", block=False, group="moderation.report")
def report(request, slug: str):
    profile = _reportable_profile(slug)
    if not feature("reports"):
        return _reports_closed(request, profile)
    form = ReportForm(request.POST or None)
    if request.method == "POST":
        if getattr(request, "limited", False):
            return _noindex(
                render(
                    request, "moderation/report.html", {"profile": profile, "form": form, "limited": True}, status=429
                )
            )
        if form.is_valid():
            if not form.is_spam():
                services.create_report(
                    profile,
                    form.cleaned_data["reason"],
                    message=form.cleaned_data["message"],
                    contact=form.cleaned_data["contact"],
                    ip_hash=security_ip_hash(request),
                )
            return _noindex(HttpResponseRedirect(reverse("moderation:report_thanks", args=[profile.slug])))
    return _noindex(render(request, "moderation/report.html", {"profile": profile, "form": form}))


def report_thanks(request, slug: str):
    profile = _reportable_profile(slug)
    return _noindex(render(request, "moderation/thanks.html", {"profile": profile}))
