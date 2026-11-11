"""KPIs shown on the admin index (templates/admin/index.html, tag apps.core.templatetags.admin_kpis)."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def get_kpis() -> dict:
    from apps.billing.models import Subscription
    from apps.cards.models import Card
    from apps.moderation.models import Report
    from apps.profiles.models import Profile
    from apps.seo.models import IndexingLog

    now = timezone.now()
    profiles = Profile.objects.exclude(status=Profile.Status.DELETED)
    total = profiles.count()
    indexable = profiles.filter(is_indexable=True).count()
    cards = dict(Card.objects.values_list("status").annotate(n=Count("id")).order_by())
    subs = (
        Subscription.objects.filter(status=Subscription.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now)
        .values("plan__name")
        .annotate(n=Count("profile", distinct=True))
        .order_by("plan__name")
    )
    return {
        "profiles_total": total,
        "profiles_indexable": indexable,
        "indexable_pct": round(100 * indexable / total) if total else 0,
        "profiles_suspended": profiles.filter(status=Profile.Status.SUSPENDED).count(),
        "profiles_last_7": profiles.filter(created_at__gte=now - timedelta(days=7)).count(),
        "profiles_last_30": profiles.filter(created_at__gte=now - timedelta(days=30)).count(),
        "cards": [{"status": s.value, "label": s.label, "count": cards.get(s.value, 0)} for s in Card.Status],
        "subscriptions": [{"plan": row["plan__name"], "count": row["n"]} for row in subs],
        "open_reports": Report.objects.filter(status=Report.Status.OPEN).count(),
        "indexing_failures": list(IndexingLog.objects.filter(success=False).order_by("-created_at")[:5]),
    }


def get_platform_state() -> dict:
    """State chips of the admin index hero (control center switches) + latest audit entries."""

    from apps.platform.services import get_settings

    s = get_settings()
    chips = [
        {"label": _("OTP WhatsApp"), "on": s.otp_whatsapp_enabled},
        {"label": _("OTP SMS Firebase"), "on": s.otp_firebase_sms_enabled},
        {"label": _("OTP SMS passerelle"), "on": s.otp_sms_gateway_enabled},
        {"label": _("Connexion"), "on": s.login_enabled},
        {"label": _("Inscriptions"), "on": s.signups_enabled},
        {"label": _("Activation des cartes"), "on": s.card_activation_enabled},
        {"label": _("Signalements"), "on": s.reports_enabled},
    ]
    return {
        "chips": chips,
        "maintenance": s.maintenance_mode,
        "announcement": s.announcement,
    }


def get_recent_audit(limit: int = 8) -> list:
    from apps.platform.models import AuditLog

    return list(AuditLog.objects.select_related("actor")[:limit])
