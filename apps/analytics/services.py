"""Analytics services: event recording, bot filtering, daily aggregation and dashboard stats.

Privacy (plan §7): no raw IP is stored, only a salted hash that rotates every day; raw events are
purged after 13 months, aggregates (DailyStat) are kept.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse

from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest
from django.utils import timezone

from apps.core.utils import client_ip, hash_ip
from apps.profiles.models import Profile

from .models import DailyStat, Event

# Crawlers, link-preview fetchers (WhatsApp, Facebook, Telegram, Slack…) and scripted clients.
BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|facebookexternalhit|facebookcatalog|whatsapp|telegram|preview|"
    r"embedly|headless|lighthouse|pingdom|curl|wget|python-requests|python-urllib|httpclient|"
    r"go-http-client|java/|okhttp|scrapy|monitor",
    re.IGNORECASE,
)
TABLET_RE = re.compile(r"ipad|tablet|kindle|silk|playbook|(android(?!.*mobile))", re.IGNORECASE)
MOBILE_RE = re.compile(r"mobi|iphone|ipod|android|opera mini|blackberry|windows phone", re.IGNORECASE)

CLICK_KINDS = frozenset(
    {
        Event.Kind.CLICK_CALL,
        Event.Kind.CLICK_WHATSAPP,
        Event.Kind.CLICK_EMAIL,
        Event.Kind.CLICK_MAPS,
        Event.Kind.CLICK_VCARD,
        Event.Kind.CLICK_LINK,
        Event.Kind.SHARE,
    }
)
RAW_EVENT_RETENTION_DAYS = 395  # 13 months


def is_bot(user_agent: str) -> bool:
    """An empty User-Agent is treated as a bot: real browsers always send one."""
    user_agent = (user_agent or "").strip()
    return not user_agent or bool(BOT_RE.search(user_agent))


def detect_device(user_agent: str) -> str:
    user_agent = user_agent or ""
    if TABLET_RE.search(user_agent):
        return "tablet"
    if MOBILE_RE.search(user_agent):
        return "mobile"
    return "desktop" if user_agent else ""


def referer_domain(request: HttpRequest) -> str:
    """Domain of the referring page; empty for direct traffic and internal navigation."""
    referer = request.META.get("HTTP_REFERER", "")
    if not referer:
        return ""
    try:
        host = (urlparse(referer).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    own = request.get_host().split(":")[0].lower().removeprefix("www.")
    if host == own:
        return ""
    return host[:120]


def record_event(profile: Profile, kind: str, request: HttpRequest, card=None) -> Event:
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    return Event.objects.create(
        profile=profile,
        card=card,
        kind=kind,
        referer_domain=referer_domain(request),
        device=detect_device(user_agent),
        is_bot=is_bot(user_agent),
        visitor_hash=hash_ip(client_ip(request)),
    )


# --- Aggregation -----------------------------------------------------------------------------


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)
    return start, end


def _count_day(day: date, profile: Profile | None = None):
    start, end = _day_bounds(day)
    qs = Event.objects.filter(created_at__gte=start, created_at__lt=end, is_bot=False)
    if profile is not None:
        qs = qs.filter(profile=profile)
    return qs.values("profile_id", "kind").annotate(total=Count("id"), unique=Count("visitor_hash", distinct=True))


@transaction.atomic
def aggregate_day(day: date) -> int:
    """(Re)build the DailyStat rows of `day` from raw events, bots excluded. Idempotent."""
    rows = list(_count_day(day))
    DailyStat.objects.filter(day=day).delete()
    DailyStat.objects.bulk_create(
        [
            DailyStat(
                profile_id=row["profile_id"],
                day=day,
                kind=row["kind"],
                total=row["total"],
                unique_visitors=row["unique"],
            )
            for row in rows
        ]
    )
    return len(rows)


def purge_old_events(now: datetime | None = None) -> int:
    cutoff = (now or timezone.now()) - timedelta(days=RAW_EVENT_RETENTION_DAYS)
    deleted, _detail = Event.objects.filter(created_at__lt=cutoff).delete()
    return deleted


# --- Dashboard -------------------------------------------------------------------------------


def stats_for_profile(profile: Profile, days: int = 30) -> dict:
    """Totals per kind and a daily series over the last `days` days (today included).

    Past days come from DailyStat; today is counted live from raw events (not aggregated yet).
    Returns {"days", "start", "end", "totals": {kind: n}, "unique_visitors": n,
             "series": [{"day": date, "<kind>": n, ...}]} — every kind is present (0 by default).
    """
    days = max(int(days), 1)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    kinds = [k.value for k in Event.Kind]
    by_day: dict[date, dict] = {start + timedelta(days=i): dict.fromkeys(kinds, 0) for i in range(days)}
    unique = 0
    for stat in DailyStat.objects.filter(profile=profile, day__gte=start, day__lt=today):
        if stat.day in by_day and stat.kind in by_day[stat.day]:
            by_day[stat.day][stat.kind] += stat.total
            if stat.kind == Event.Kind.VISIT:
                unique += stat.unique_visitors
    for row in _count_day(today, profile):
        by_day[today][row["kind"]] += row["total"]
        if row["kind"] == Event.Kind.VISIT:
            unique += row["unique"]
    totals = dict.fromkeys(kinds, 0)
    for counts in by_day.values():
        for kind, n in counts.items():
            totals[kind] += n
    return {
        "days": days,
        "start": start,
        "end": today,
        "totals": totals,
        "unique_visitors": unique,
        "contacts": sum(totals[k] for k in CLICK_KINDS),
        "series": [{"day": day, **counts} for day, counts in sorted(by_day.items())],
    }
