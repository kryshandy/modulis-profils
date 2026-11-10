"""Moderation: public reports and their handling (plan §7, "Arnaques")."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.profiles import services as profile_services
from apps.profiles.models import Profile

from .models import Report

DUPLICATE_BIO_MARKER = "[auto:bio-dupliquee]"


def create_report(profile: Profile, reason: str, *, message: str = "", contact: str = "", ip_hash: str = "") -> Report:
    return Report.objects.create(
        profile=profile,
        reason=reason,
        message=(message or "").strip()[:1000],
        reporter_contact=(contact or "").strip()[:120],
        reporter_ip_hash=ip_hash,
    )


def report_duplicate_bio(profile: Profile, original: Profile) -> Report | None:
    """Automatic report: `profile` copies the bio of the older page `original` (SEO audit).

    At most ONE open automatic report per profile: returns None when one is already open.
    """
    if Report.objects.filter(
        profile=profile, status=Report.Status.OPEN, message__startswith=DUPLICATE_BIO_MARKER
    ).exists():
        return None
    message = _("%(marker)s Présentation quasi identique à celle de /%(slug)s (profil n° %(pk)d).") % {
        "marker": DUPLICATE_BIO_MARKER,
        "slug": original.slug,
        "pk": original.pk,
    }
    return create_report(profile, Report.Reason.SPAM, message=message)


def open_reports_count() -> int:
    return Report.objects.filter(status=Report.Status.OPEN).count()


@transaction.atomic
def close_report(report: Report, status: str, *, by=None, note: str = "") -> Report:
    report.status = status
    report.handled_by = by
    report.handled_at = timezone.now()
    if note:
        report.resolution_note = note
    report.save(update_fields=["status", "handled_by", "handled_at", "resolution_note"])
    return report


@transaction.atomic
def suspend_reported_profile(report: Report, *, by=None, note: str = "") -> Profile:
    """Suspend the profile and close every open report about it (this one included) as "action taken".

    Each report is closed exactly once: `report` itself is handled in the same loop as the others.
    """
    profile = report.profile
    if profile.status == Profile.Status.ACTIVE:
        profile_services.suspend_profile(profile, f"{report.get_reason_display()} (signalement #{report.pk})")
    pending = list(Report.objects.select_for_update().filter(profile=profile, status=Report.Status.OPEN))
    if report.status != Report.Status.ACTIONED and all(r.pk != report.pk for r in pending):
        pending.append(report)
    for open_report in pending:
        close_report(open_report, Report.Status.ACTIONED, by=by, note=note)
        if open_report.pk == report.pk:
            report.status, report.handled_by, report.handled_at = (
                open_report.status,
                open_report.handled_by,
                open_report.handled_at,
            )
            report.resolution_note = open_report.resolution_note
    return profile
