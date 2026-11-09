"""Tracking endpoints: a 1x1 visit pixel and a click beacon. Both are cheap and never fail loudly."""

import base64

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.utils import ratelimit_ip_key
from apps.profiles.models import Profile

from . import services
from .models import Event

# Smallest transparent GIF (43 bytes).
PIXEL_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def _public_profile(profile_id: int) -> Profile | None:
    return Profile.objects.filter(
        pk=profile_id, status=Profile.Status.ACTIVE, visibility=Profile.Visibility.PUBLIC
    ).first()


def _is_owner(request, profile: Profile) -> bool:
    return request.user.is_authenticated and request.user.pk == profile.user_id


@require_GET
@never_cache
@ratelimit(key=ratelimit_ip_key, rate="120/m", block=False, group="analytics.pixel")
def pixel(request, profile_id: int):
    profile = None if getattr(request, "limited", False) else _public_profile(profile_id)
    if profile is not None and not _is_owner(request, profile):
        services.record_event(profile, Event.Kind.VISIT, request)
    response = HttpResponse(PIXEL_GIF, content_type="image/gif")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@csrf_exempt  # sent with navigator.sendBeacon from public pages; it changes nothing but a counter
@require_POST
@ratelimit(key=ratelimit_ip_key, rate="60/m", block=False, group="analytics.click")
def click(request, profile_id: int, kind: str):
    if kind not in services.CLICK_KINDS:
        return HttpResponseBadRequest()
    if getattr(request, "limited", False):
        return HttpResponse(status=429)
    profile = _public_profile(profile_id)
    if profile is not None and not _is_owner(request, profile):
        services.record_event(profile, kind, request)
    response = HttpResponse(status=204)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
