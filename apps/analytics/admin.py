from django.contrib import admin

from .models import DailyStat, Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "profile", "card", "device", "referer_domain", "is_bot")
    list_filter = ("kind", "is_bot", "device", "created_at")
    search_fields = ("profile__slug", "profile__display_name", "referer_domain")
    list_select_related = ("profile", "card")
    date_hierarchy = "created_at"
    show_full_result_count = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DailyStat)
class DailyStatAdmin(admin.ModelAdmin):
    list_display = ("day", "profile", "kind", "total", "unique_visitors")
    list_filter = ("kind", "day")
    search_fields = ("profile__slug", "profile__display_name")
    list_select_related = ("profile",)
    date_hierarchy = "day"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
