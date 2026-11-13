"""Acceptance of the current CGU + privacy policy by pro accounts."""

from __future__ import annotations

from django.utils import timezone

from .conf import LEGAL_VERSION


def needs_acceptance(user) -> bool:
    """True for a logged-in pro account that has not accepted the current version yet."""
    if not getattr(user, "is_authenticated", False) or user.is_staff or user.is_superuser:
        return False
    return user.terms_version != LEGAL_VERSION


def record_acceptance(user) -> None:
    from apps.accounts.models import User

    now = timezone.now()
    User.objects.filter(pk=user.pk).update(terms_version=LEGAL_VERSION, terms_accepted_at=now)
    user.terms_version, user.terms_accepted_at = LEGAL_VERSION, now


# Privacy policy §7: handled reports and the staff audit log are kept 3 years.
AUDIT_LOG_RETENTION_DAYS = 3 * 365
HANDLED_REPORT_RETENTION_DAYS = 3 * 365


def purge_expired_records(now=None) -> dict:
    from datetime import timedelta

    from apps.moderation.models import Report
    from apps.platform.models import AuditLog

    now = now or timezone.now()
    audit_deleted, _ = AuditLog.objects.filter(created_at__lt=now - timedelta(days=AUDIT_LOG_RETENTION_DAYS)).delete()
    reports_deleted, _ = (
        Report.objects.exclude(status=Report.Status.OPEN)
        .filter(created_at__lt=now - timedelta(days=HANDLED_REPORT_RETENTION_DAYS))
        .delete()
    )
    return {"audit_log": audit_deleted, "reports": reports_deleted}
