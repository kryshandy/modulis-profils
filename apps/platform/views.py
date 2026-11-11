"""Control center ("centre de contrôle"): custom admin views mounted on admin.site (see admin.py).

Every view here is wrapped by admin.site.admin_view (active staff only) and additionally requires
the permission platform_settings.manage_platform (superusers have it implicitly).
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _

from . import health, services
from .forms import OTP_FLAGS, SECTIONS, SECTIONS_BY_CODE, build_forms
from .middleware import render_maintenance
from .models import AuditLog, SiteSettings

logger = logging.getLogger(__name__)

PERMISSION = "platform_settings.manage_platform"


def can_manage(user) -> bool:
    return bool(user.is_active and user.is_staff and user.has_perm(PERMISSION))


def _require(request):
    if not can_manage(request.user):
        raise PermissionDenied


def otp_channels(current: SiteSettings) -> list[dict]:
    """Admin switch + provider configuration for each OTP channel.

    The configuration comes from apps.accounts.otp.registry.channel_status() when available
    ([{code, label, enabled, configured, kind}]); `configured` is None when unknown.
    """
    status: dict[str, dict] | None
    try:
        from apps.accounts.otp.registry import channel_status

        status = {str(row.get("code")): row for row in channel_status()}
    except Exception:  # registry not built yet, or a provider check failing: never break the admin
        logger.debug("OTP channel registry unavailable", exc_info=True)
        status = None
    rows = []
    for code, flag in OTP_FLAGS.items():
        info = (status or {}).get(str(code), {})
        rows.append(
            {
                "code": str(code),
                "label": SiteSettings.OtpChannel(code).label,
                "enabled": getattr(current, flag),
                "configured": info.get("configured") if info else None,
                "kind": info.get("kind", ""),
                "is_default": current.otp_default_channel == code,
            }
        )
    return rows


def _context(request, settings_obj: SiteSettings, forms_: dict, **extra) -> dict:
    from django.contrib import admin

    return {
        **admin.site.each_context(request),
        "title": _("Centre de contrôle"),
        "settings_obj": settings_obj,
        "sections": [(section, forms_[section.code]) for section in SECTIONS],
        "otp_channels": otp_channels(settings_obj),
        "health": health.report(),
        "seo": health.seo_summary(),
        "recent_audit": AuditLog.objects.select_related("actor")[:10],
        **extra,
    }


def _current() -> SiteSettings:
    return SiteSettings.objects.get_or_create(pk=1)[0]  # fresh from the DB, never the cached copy


def control_center(request):
    _require(request)
    current = _current()
    if request.method != "POST":
        return TemplateResponse(
            request, "admin/platform/control_center.html", _context(request, current, build_forms(current))
        )

    code = request.POST.get("section", "")
    if code == "seo_flush":
        return _flush_indexing(request)
    section = SECTIONS_BY_CODE.get(code)
    if section is None:
        messages.error(request, _("Section inconnue."))
        return redirect("admin:platform_control_center")

    forms_ = build_forms(current, bound_section=code, data=request.POST)
    form = forms_[code]
    if not form.is_valid():
        messages.error(request, _("Corrige les erreurs de la section « %(s)s ».") % {"s": section.title})
        return TemplateResponse(
            request, "admin/platform/control_center.html", _context(request, current, forms_, open_section=code)
        )

    warnings = form.dangerous_changes(current)
    if warnings and request.POST.get("confirm") != "1":
        hidden = [
            (key, value)
            for key, values in request.POST.lists()
            if key not in ("csrfmiddlewaretoken", "confirm")
            for value in values
        ]
        context = {
            **_context(request, current, forms_),
            "title": _("Confirmer le changement"),
            "section": section,
            "warnings": warnings,
            "hidden_fields": hidden,
        }
        return TemplateResponse(request, "admin/platform/confirm.html", context)

    values = {name: form.cleaned_data[name] for name in section.fields}
    changes = services.update_settings(request.user, code, values)
    if changes:
        messages.success(request, _("Section « %(s)s » enregistrée.") % {"s": section.title})
        if code == "auth" and not any(values[f] for f in OTP_FLAGS.values()):
            messages.warning(request, _("Aucun canal OTP n'est actif : plus personne ne peut recevoir de code."))
    else:
        messages.info(request, _("Aucun changement dans « %(s)s ».") % {"s": section.title})
    return redirect(reverse("admin:platform_control_center") + f"#section-{code}")


def _flush_indexing(request):
    from apps.seo.tasks import flush_indexing_queue

    try:
        flush_indexing_queue()
    except Exception:
        logger.exception("manual indexing flush failed")
        messages.error(request, _("La notification des moteurs a échoué : consulte le journal d'indexation."))
    else:
        services.audit(request.user, "seo.flush", "IndexingQueue")
        messages.success(request, _("Notification des moteurs lancée (file d'indexation envoyée en tâche de fond)."))
    return redirect(reverse("admin:platform_control_center") + "#section-seo")


def maintenance_preview(request):
    """What visitors see when maintenance is on (status 200 here, 503 for real)."""
    _require(request)
    response = render_maintenance(request, status=200, preview=True)
    return response
