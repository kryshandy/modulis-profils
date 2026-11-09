from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from . import services
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "reason", "profile_link", "profile_status", "status", "handled_by", "handled_at")
    list_filter = ("status", "reason", "created_at", "profile__status")
    search_fields = ("profile__slug", "profile__display_name", "profile__user__phone", "message", "reporter_contact")
    list_select_related = ("profile", "handled_by")
    date_hierarchy = "created_at"
    readonly_fields = (
        "profile_link",
        "profile_status",
        "reason",
        "message",
        "reporter_contact",
        "reporter_ip_hash",
        "created_at",
        "handled_by",
        "handled_at",
    )
    fields = (*readonly_fields[:7], "status", "resolution_note", "handled_by", "handled_at")
    actions = ("suspend_profile", "dismiss", "mark_actioned")

    @admin.display(description=_("profil"), ordering="profile__slug")
    def profile_link(self, obj):
        url = reverse("admin:profiles_profile_change", args=[obj.profile_id])
        return format_html(
            '<a href="{}">{}</a> · <a href="{}" target="_blank" rel="noopener">{}</a>',
            url,
            obj.profile.display_name,
            obj.profile.get_absolute_url(),
            _("voir la page"),
        )

    @admin.display(description=_("statut du profil"))
    def profile_status(self, obj):
        return obj.profile.get_status_display()

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        if change and "status" in form.changed_data:
            obj.handled_by = request.user
            obj.handled_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Suspendre le profil"))
    def suspend_profile(self, request, queryset):
        profiles = set()
        for report in queryset.select_related("profile"):
            if report.profile_id in profiles:
                continue
            services.suspend_reported_profile(report, by=request.user)
            profiles.add(report.profile_id)
        self.message_user(request, _("%(n)d profil(s) suspendu(s).") % {"n": len(profiles)}, messages.SUCCESS)

    @admin.action(description=_("Classer sans suite"))
    def dismiss(self, request, queryset):
        for report in queryset:
            services.close_report(report, Report.Status.DISMISSED, by=request.user)
        self.message_user(request, _("Signalement(s) classé(s) sans suite."), messages.SUCCESS)

    @admin.action(description=_("Mesure prise"))
    def mark_actioned(self, request, queryset):
        for report in queryset:
            services.close_report(report, Report.Status.ACTIONED, by=request.user)
        self.message_user(request, _("Signalement(s) marqué(s) « mesure prise »."), messages.SUCCESS)
