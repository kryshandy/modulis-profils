"""Shared helpers for dashboard views."""

from __future__ import annotations

import json
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.billing.services import current_plan_code
from apps.profiles.models import Profile

from ..services import active_profile, user_profiles


def profile_required(view):
    """Login required + an active profile owned by the user, set as `request.profile`."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        profile = active_profile(request)
        if profile is None:
            return redirect("dashboard:onboarding", step="nom")
        request.profile = profile
        return view(request, *args, **kwargs)

    return wrapper


def dash_render(request, template: str, context: dict | None = None, *, status: int = 200):
    """Render a dashboard page with the shell context (profile, switcher, plan, nav)."""
    profile: Profile | None = getattr(request, "profile", None)
    ctx = {
        "profile": profile,
        "all_profiles": list(user_profiles(request.user).select_related(None).only("id", "display_name", "slug"))
        if profile
        else [],
        "plan_code": current_plan_code(profile) if profile else "free",
    }
    ctx.update(context or {})
    return render(request, template, ctx, status=status)


def with_toast(response, message: str | None = None, *, kind: str = "success"):
    response["HX-Trigger"] = json.dumps({"toast": {"message": message or _("Enregistré ✓"), "kind": kind}})
    return response


def edit_url(section: str) -> str:
    return reverse("dashboard:edit", kwargs={"section": section})
