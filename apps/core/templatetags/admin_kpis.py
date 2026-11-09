from django import template

from apps.core.admin_dashboard import get_kpis

register = template.Library()


@register.inclusion_tag("admin/includes/kpis.html")
def admin_kpis():
    return {"kpis": get_kpis()}
