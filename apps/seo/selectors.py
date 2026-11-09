"""Read-only queries shared by the public pages and the sitemaps.

They only read profiles / reference data (no writes): a candidate to move into
profiles.services later if the team prefers a single entry point.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Count, Max, QuerySet

from apps.core.models import City, Trade
from apps.profiles.models import Profile


def indexable_profiles() -> QuerySet[Profile]:
    """Pages Google may index: active, public and above the completeness threshold."""
    return Profile.objects.filter(
        is_indexable=True, status=Profile.Status.ACTIVE, visibility=Profile.Visibility.PUBLIC
    ).select_related("trade", "city")


def directory_min() -> int:
    return settings.SEO_DIRECTORY_MIN_PROFILES


def find_city(slug: str) -> City | None:
    return (
        City.objects.select_related("country")
        .filter(slug=slug.lower(), is_active=True)
        .order_by("-country__is_active", "country_id")
        .first()
    )


def find_trade_by_plural(plural_slug: str) -> Trade | None:
    return Trade.objects.filter(plural_slug=plural_slug.lower(), is_active=True).first()


def directory_profiles(trade: Trade, city: City) -> QuerySet[Profile]:
    return indexable_profiles().filter(trade=trade, city=city).order_by("-content_updated_at", "-pk")


def city_profiles(city: City) -> QuerySet[Profile]:
    return indexable_profiles().filter(city=city).order_by("-content_updated_at", "-pk")


def directory_combos(min_count: int = 1) -> list[dict]:
    """[{trade, city, count, lastmod}] for every trade×city with at least `min_count` indexable profiles."""
    rows = (
        indexable_profiles()
        .filter(trade__isnull=False, city__isnull=False, trade__is_active=True, city__is_active=True)
        .values("trade_id", "city_id")
        .annotate(count=Count("pk"), lastmod=Max("content_updated_at"))
        .filter(count__gte=min_count)
        .order_by("-count")
    )
    rows = list(rows)
    trades = Trade.objects.in_bulk({r["trade_id"] for r in rows})
    cities = City.objects.in_bulk({r["city_id"] for r in rows})
    return [
        {"trade": trades[r["trade_id"]], "city": cities[r["city_id"]], "count": r["count"], "lastmod": r["lastmod"]}
        for r in rows
    ]


def city_stats(min_count: int = 1) -> list[dict]:
    """[{city, count, lastmod}] for active cities with at least `min_count` indexable profiles."""
    rows = list(
        indexable_profiles()
        .filter(city__isnull=False, city__is_active=True)
        .values("city_id")
        .annotate(count=Count("pk"), lastmod=Max("content_updated_at"))
        .filter(count__gte=min_count)
        .order_by("-count")
    )
    cities = City.objects.in_bulk({r["city_id"] for r in rows})
    return [{"city": cities[r["city_id"]], "count": r["count"], "lastmod": r["lastmod"]} for r in rows]


def trades_in_city(city: City) -> list[dict]:
    """[{trade, count}] of trades having indexable profiles in `city`."""
    return [c for c in directory_combos() if c["city"].pk == city.pk]


def similar_profiles(profile: Profile, limit: int = 6) -> list[Profile]:
    """« Autres plombiers à Douala » block (internal linking, plan §6.9)."""
    if not (profile.trade_id and profile.city_id):
        return []
    return list(
        indexable_profiles()
        .filter(trade_id=profile.trade_id, city_id=profile.city_id)
        .exclude(pk=profile.pk)
        .order_by("-content_updated_at", "-pk")[:limit]
    )


def active_card_code(profile: Profile) -> str | None:
    """Public code of the profile's first active card, used as the QR target (plan §4)."""
    from apps.cards.services import active_card_code as _active_card_code

    return _active_card_code(profile)
