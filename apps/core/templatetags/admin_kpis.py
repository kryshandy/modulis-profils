from django import template

from apps.core.admin_dashboard import get_kpis, get_platform_state, get_recent_audit

register = template.Library()


@register.inclusion_tag("admin/includes/kpis.html")
def admin_kpis():
    return {"kpis": get_kpis()}


@register.inclusion_tag("admin/includes/platform_hero.html", takes_context=True)
def admin_platform_hero(context):
    from apps.platform.views import can_manage

    request = context.get("request")
    user = getattr(request, "user", None)
    return {"state": get_platform_state(), "can_manage": bool(user and can_manage(user))}


@register.inclusion_tag("admin/includes/recent_audit.html", takes_context=True)
def admin_recent_audit(context):
    request = context.get("request")
    user = getattr(request, "user", None)
    show = bool(user and user.has_perm("platform_settings.view_auditlog"))
    return {"entries": get_recent_audit() if show else [], "show": show}


@register.simple_tag
def staff_two_factor():
    """Staff 2FA coverage for the control center (apps.security.services.two_factor_summary)."""
    from apps.security.services import two_factor_summary

    return two_factor_summary()
