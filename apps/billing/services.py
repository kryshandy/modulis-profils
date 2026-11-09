"""Entitlements: what a profile may do according to its current plan."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.profiles.models import Profile

from .models import Plan, Subscription

FREE_ENTITLEMENTS = {
    "hide_branding": False,
    "verified_badge": False,
    "advanced_stats": False,
    "max_profiles": 1,
    "reviews": False,
    "quotes": False,
    "featured": False,
    "free_cards": 0,
}


def current_subscription(profile: Profile) -> Subscription | None:
    now = timezone.now()
    return (
        profile.subscriptions.select_related("plan")
        .filter(status=Subscription.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now)
        .order_by("-ends_at")
        .first()
    )


def current_plan_code(profile: Profile) -> str:
    sub = current_subscription(profile)
    return sub.plan.code if sub else Plan.Code.FREE


def entitlements(profile: Profile) -> dict:
    sub = current_subscription(profile)
    if sub is None:
        return dict(FREE_ENTITLEMENTS)
    return {**FREE_ENTITLEMENTS, **sub.plan.entitlements}


def has(profile: Profile, entitlement: str) -> bool:
    return bool(entitlements(profile).get(entitlement))


@transaction.atomic
def grant_plan(
    profile: Profile, plan: Plan, *, days: int = 365, source=Subscription.Source.MANUAL, created_by=None, note: str = ""
) -> Subscription:
    """Start or extend a subscription. Renewal before expiry extends from the current end date."""
    current = current_subscription(profile)
    start = current.ends_at if current and current.plan_id == plan.pk else timezone.now()
    return Subscription.objects.create(
        profile=profile,
        plan=plan,
        starts_at=start,
        ends_at=start + timedelta(days=days),
        source=source,
        created_by=created_by,
        note=note,
    )


def expire_subscriptions() -> int:
    """Daily job: mark ended subscriptions as expired. Content is never deleted (back to free)."""
    return Subscription.objects.filter(status=Subscription.Status.ACTIVE, ends_at__lte=timezone.now()).update(
        status=Subscription.Status.EXPIRED
    )
