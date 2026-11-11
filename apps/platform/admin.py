"""Admin of the platform app: control center URLs, blocked phones, audit log.

The control center lives at /<ADMIN_URL>/centre-de-controle/ (URL name "admin:platform_control_center").
It is mounted on the default admin site by extending admin.site.get_urls; the SiteSettings
changelist and change form simply redirect there.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import services, views
from .models import AuditLog, BlockedPhone, SiteSettings

# --- Control center URLs ---------------------------------------------------------------------


def _control_center_urls():
    site = admin.site
    return [
        path("centre-de-controle/", site.admin_view(views.control_center), name="platform_control_center"),
        path(
            "centre-de-controle/apercu-maintenance/",
            site.admin_view(views.maintenance_preview),
            name="platform_maintenance_preview",
        ),
    ]


if not getattr(admin.site, "_platform_urls_installed", False):
    _base_get_urls = admin.site.get_urls

    def _get_urls():
        return _control_center_urls() + _base_get_urls()

    admin.site.get_urls = _get_urls
    admin.site._platform_urls_installed = True


# --- SiteSettings: redirect to the control center ----------------------------------------------


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return views.can_manage(request.user)

    def has_module_permission(self, request):
        return views.can_manage(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return redirect("admin:platform_control_center")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return redirect("admin:platform_control_center")


# --- Blocked phones ----------------------------------------------------------------------------


class BlockedPhoneForm(forms.ModelForm):
    class Meta:
        model = BlockedPhone
        fields = ("phone", "reason")

    def clean_phone(self):
        from apps.accounts.services import OTPError, normalize_phone

        try:
            return normalize_phone(self.cleaned_data.get("phone", ""))
        except OTPError as exc:
            raise forms.ValidationError(str(exc)) from exc


@admin.register(BlockedPhone)
class BlockedPhoneAdmin(admin.ModelAdmin):
    form = BlockedPhoneForm
    list_display = ("phone", "reason", "created_by", "created_at")
    search_fields = ("phone", "reason")
    list_filter = ("created_at",)
    readonly_fields = ("created_by", "created_at")
    list_select_related = ("created_by",)
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):
        return (*self.readonly_fields, "phone") if obj else self.readonly_fields

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            services.audit(request.user, "phone.block_update", obj.phone, reason=obj.reason)
            return
        # Creation goes through the service: deactivates the account and logs it out everywhere.
        blocked = services.block_phone(obj.phone, reason=obj.reason, actor=request.user)
        obj.pk = blocked.pk
        messages.info(request, _("Le compte lié à ce numéro (s'il existe) a été désactivé et déconnecté."))

    def delete_model(self, request, obj):
        services.unblock_phone(obj.phone, actor=request.user, reactivate=False)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            services.unblock_phone(obj.phone, actor=request.user, reactivate=False)


# --- Audit log (read-only) ---------------------------------------------------------------------


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target", "short_details")
    list_filter = ("action", "created_at", ("actor", admin.RelatedOnlyFieldListFilter))
    search_fields = ("action", "target", "actor__phone", "actor__full_name")
    list_select_related = ("actor",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "actor", "action", "target", "details")

    @admin.display(description=_("détails"))
    def short_details(self, obj):
        text = ", ".join(f"{k}={v}" for k, v in (obj.details or {}).items())
        return text[:140] + ("…" if len(text) > 140 else "")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
