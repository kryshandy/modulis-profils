"""Moderation: public reports and their handling (plan §7, "Arnaques")."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.profiles import services as profile_services
from apps.profiles.models import Profile

from .models import Report


def create_report(profile: Profile, reason: str, *, message: str = "", contact: str = "", ip_hash: str = "") -> Report:
    return Report.objects.create(
        profile=profile,
        reason=reason,
        message=(message or "").strip()[:1000],
        reporter_contact=(contact or "").strip()[:120],
        reporter_ip_hash=ip_hash,
    )


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
    """Suspend the profile and close every open report about it as "action taken"."""
    profile = report.profile
    if profile.status == Profile.Status.ACTIVE:
        profile_services.suspend_profile(profile, f"{report.get_reason_display()} (signalement #{report.pk})")
    for open_report in Report.objects.filter(profile=profile, status=Report.Status.OPEN):
        close_report(open_report, Report.Status.ACTIONED, by=by, note=note)
    if report.status != Report.Status.ACTIONED:
        close_report(report, Report.Status.ACTIONED, by=by, note=note)
    return profile
