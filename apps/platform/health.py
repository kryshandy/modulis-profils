"""Health panel of the control center: cheap checks only (one query or cache call each)."""

from __future__ import annotations

import platform as py_platform
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import django
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import services

OK, WARN, ERROR = "ok", "warn", "error"


@dataclass
class Check:
    label: str
    state: str  # ok | warn | error
    value: str
    detail: str = ""
    url: str = ""
    extra: dict = field(default_factory=dict)


def _database() -> Check:
    start = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:  # pragma: no cover - only when the DB is down
        return Check(str(_("Base de données")), ERROR, str(_("injoignable")), str(exc)[:200])
    ms = (time.perf_counter() - start) * 1000
    return Check(str(_("Base de données")), OK if ms < 200 else WARN, f"{ms:.0f} ms", connection.vendor)


def _cache() -> Check:
    key, value = "platform:health:probe", uuid.uuid4().hex
    try:
        cache.set(key, value, 30)
        ok = cache.get(key) == value
    except Exception as exc:  # pragma: no cover - only when Redis is down
        return Check(str(_("Cache")), ERROR, str(_("injoignable")), str(exc)[:200])
    backend = settings.CACHES["default"]["BACKEND"].rsplit(".", 1)[-1]
    return Check(str(_("Cache")), OK if ok else ERROR, str(_("lecture/écriture OK") if ok else _("échec")), backend)


def _heartbeat() -> Check:
    age = services.heartbeat_age()
    label = str(_("Tâches de fond (Huey)"))
    if age is None:
        return Check(label, WARN, str(_("jamais vu")), str(_("Le worker n'a pas encore signalé sa présence.")))
    minutes = int(age // 60)
    value = str(_("il y a %(n)d min") % {"n": minutes}) if minutes else str(_("à l'instant"))
    if age > services.HEARTBEAT_LATE_SECONDS:
        return Check(label, ERROR, str(_("en retard")), value)
    return Check(label, OK, value)


def _kliz() -> Check:
    from apps.seo.models import IndexingLog

    label = str(_("Dernière notification kliz"))
    last = IndexingLog.objects.order_by("-created_at").first()
    if last is None:
        return Check(label, WARN if settings.KLIZ_ENABLED else OK, str(_("aucune")))
    when = timezone.localtime(last.created_at).strftime("%d/%m/%Y %H:%M")
    return Check(label, OK if last.success else ERROR, when, f"{last.provider} · {'OK' if last.success else 'ÉCHEC'}")


def _counts() -> list[Check]:
    from django.urls import reverse

    from apps.cards.models import CardActivationAttempt
    from apps.moderation.models import Report
    from apps.profiles.models import Profile

    open_reports = Report.objects.filter(status=Report.Status.OPEN).count()
    suspended = Profile.objects.filter(status=Profile.Status.SUSPENDED).count()
    failures = CardActivationAttempt.objects.filter(
        success=False, created_at__gte=timezone.now() - timedelta(hours=24)
    ).count()
    return [
        Check(
            str(_("Signalements ouverts")),
            WARN if open_reports else OK,
            str(open_reports),
            url=reverse("admin:moderation_report_changelist") + "?status__exact=open",
        ),
        Check(
            str(_("Pages suspendues")),
            OK,
            str(suspended),
            url=reverse("admin:profiles_profile_changelist") + "?status__exact=suspended",
        ),
        Check(
            str(_("Échecs d'activation de carte (24 h)")),
            WARN if failures >= 20 else OK,
            str(failures),
            url=reverse("admin:cards_cardactivationattempt_changelist") + "?success__exact=0",
        ),
    ]


def _runtime() -> list[Check]:
    checks = [
        Check(
            str(_("Versions")),
            OK,
            f"Python {py_platform.python_version()} · Django {django.get_version()}",
        )
    ]
    if settings.DEBUG:
        checks.append(
            Check(
                str(_("Mode DEBUG")),
                ERROR,
                str(_("ACTIVÉ")),
                str(_("Ne jamais laisser DEBUG actif en production (fuite d'informations).")),
            )
        )
    return checks


def report() -> list[Check]:
    return [_database(), _cache(), _heartbeat(), _kliz(), *_counts(), *_runtime()]


def seo_summary() -> dict:
    from apps.seo.models import IndexingLog, IndexingQueue

    return {
        "queue_size": IndexingQueue.objects.count(),
        "successes": list(IndexingLog.objects.filter(success=True).order_by("-created_at")[:5]),
        "failures": list(IndexingLog.objects.filter(success=False).order_by("-created_at")[:5]),
        "kliz_enabled": settings.KLIZ_ENABLED,
    }
