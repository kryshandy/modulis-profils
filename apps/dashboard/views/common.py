"""Shared helpers for dashboard views."""

from __future__ import annotations

import json
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.billing.services import current_plan_code
from apps.profiles.models import Profile

from ..services import active_profile, user_profiles

SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")


def is_suspended(profile: Profile | None) -> bool:
    return profile is not None and profile.status == Profile.Status.SUSPENDED


def suspended_response(request, profile: Profile):
    """403 for any change attempted on a suspended page: explain why and who to contact."""
    message = _("Ta page est suspendue : tu ne peux pas la modifier. Contacte le support Modulis.")
    if getattr(request, "htmx", False):
        return with_toast(HttpResponse(status=403), message, kind="error")
    request.profile = profile
    support = getattr(settings, "SUPPORT_WHATSAPP", "") or ""
    return dash_render(
        request,
        "dashboard/suspended.html",
        {"suspended_reason": profile.suspended_reason, "support_whatsapp": support.lstrip("+")},
        status=403,
    )


def profile_required(view=None, *, allow_suspended: bool = False):
    """Login required + an active profile owned by the user, set as `request.profile`.

    A SUSPENDED page can still be viewed, but every state-changing request (POST…) is refused
    with a 403 explanation page, unless `allow_suspended` (e.g. switching to another page).
    """

    def decorator(func):
        @login_required
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            profile = active_profile(request)
            if profile is None:
                return redirect("dashboard:onboarding", step="nom")
            if is_suspended(profile) and request.method not in SAFE_METHODS and not allow_suspended:
                return suspended_response(request, profile)
            request.profile = profile
            return func(request, *args, **kwargs)

        return wrapper

    return decorator(view) if view is not None else decorator


def dash_render(request, template: str, context: dict | None = None, *, status: int = 200):
    """Render a dashboard page with the shell context (profile, switcher, plan, nav)."""
    profile: Profile | None = getattr(request, "profile", None)
    ctx = {
        "profile": profile,
        "all_profiles": list(user_profiles(request.user).select_related(None).only("id", "display_name", "slug"))
        if profile
        else [],
        "plan_code": current_plan_code(profile) if profile else "free",
        "profile_suspended": is_suspended(profile),
    }
    ctx.update(context or {})
    return render(request, template, ctx, status=status)


def with_toast(response, message: str | None = None, *, kind: str = "success"):
    response["HX-Trigger"] = json.dumps({"toast": {"message": message or _("Enregistré ✓"), "kind": kind}})
    return response


def edit_url(section: str) -> str:
    return reverse("dashboard:edit", kwargs={"section": section})
