"""Team view of the page builder blocks: read, moderate (hide / restore), never edit the pro's words."""

import json

from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from . import services
from .models import BlockImage, PageBlock


class BlockImageInline(admin.TabularInline):
    model = BlockImage
    fields = ("slot", "preview", "width", "height", "created_at")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description=_("aperçu"))
    def preview(self, obj):
        return format_html('<img src="{}" alt="" width="120" loading="lazy">', obj.image.url) if obj.image else "—"


@admin.register(PageBlock)
class PageBlockAdmin(admin.ModelAdmin):
    list_display = ("__str__", "page", "kind", "moderated", "updated_at")
    list_filter = ("moderated", "kind", "updated_at")
    search_fields = ("profile__slug", "profile__display_name", "data")
    list_select_related = ("profile",)
    readonly_fields = ("profile", "kind", "content", "style", "created_at", "updated_at")
    fields = ("profile", "kind", "content", "style", "moderated", "moderation_note", "created_at", "updated_at")
    inlines = [BlockImageInline]
    actions = ("hide_blocks", "restore_blocks")

    def has_add_permission(self, request):
        return False  # blocks are written by the pros, in their own words

    @admin.display(description=_("page"), ordering="profile__slug")
    def page(self, obj):
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">/{}#{}</a>',
            obj.profile.get_absolute_url(),
            obj.profile.slug,
            obj.anchor,
        )

    @admin.display(description=_("contenu"))
    def content(self, obj):
        return format_html(
            '<pre class="mp-json">{}</pre>',
            json.dumps(obj.data, ensure_ascii=False, indent=2),
        )

    def save_model(self, request, obj, form, change):
        if change and {"moderated", "moderation_note"} & set(form.changed_data):
            services.moderate(obj, hidden=obj.moderated, note=obj.moderation_note, actor=request.user)
            return
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Masquer les blocs (modération)"), permissions=["change"])
    def hide_blocks(self, request, queryset):
        for block in queryset:
            services.moderate(
                block, hidden=True, note=block.moderation_note or "Masqué par l'équipe", actor=request.user
            )
        n = queryset.count()
        self.message_user(request, ngettext("%d bloc masqué.", "%d blocs masqués.", n) % n, messages.SUCCESS)

    @admin.action(description=_("Réafficher les blocs"), permissions=["change"])
    def restore_blocks(self, request, queryset):
        for block in queryset:
            services.moderate(block, hidden=False, actor=request.user)
        n = queryset.count()
        self.message_user(request, ngettext("%d bloc réaffiché.", "%d blocs réaffichés.", n) % n, messages.SUCCESS)
