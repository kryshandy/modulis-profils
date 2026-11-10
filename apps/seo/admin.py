from django.contrib import admin

from .models import IndexingLog, IndexingQueue


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(IndexingQueue)
class IndexingQueueAdmin(ReadOnlyAdmin):
    list_display = ("url", "queued_at", "not_before")
    search_fields = ("url",)
    date_hierarchy = "queued_at"


@admin.register(IndexingLog)
class IndexingLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "provider", "success", "url_count", "status_code", "attempts", "sample_url")
    list_filter = ("success", "provider", "created_at")
    search_fields = ("sample_url", "error")
    date_hierarchy = "created_at"
