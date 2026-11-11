from django.contrib import admin, messages
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from .models import ProfileTheme, Theme


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "layout", "font_pair", "is_active", "is_premium", "order", "usage")
    list_editable = ("is_active", "is_premium", "order")
    list_filter = ("is_active", "is_premium", "category", "layout")
    search_fields = ("name", "code", "description")
    ordering = ("order", "name")
    actions = ("activate", "deactivate", "make_premium", "make_free")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "code", "category", "description", "is_active", "is_premium", "order")}),
        (_("Design par défaut"), {"fields": ("layout", "palette", "palette_presets", "font_pair", "corners")}),
        (_("Contenu par défaut"), {"fields": ("sections", "cta_label")}),
        (_("Historique"), {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_usage=Count("profile_themes"))

    @admin.display(description=_("pages"), ordering="_usage")
    def usage(self, obj):
        return obj._usage

    def get_readonly_fields(self, request, obj=None):
        # The code is referenced by drafts and by the default-theme logic: frozen once created.
        return (*self.readonly_fields, "code") if obj else self.readonly_fields

    def _bulk(self, request, queryset, message, **values):
        count = queryset.update(**values)
        self.message_user(request, message % {"n": count}, messages.SUCCESS)

    @admin.action(permissions=("change",), description=_("Activer (visible dans la galerie)"))
    def activate(self, request, queryset):
        self._bulk(request, queryset, _("%(n)d modèle(s) activé(s)."), is_active=True)

    @admin.action(permissions=("change",), description=_("Désactiver (les pages qui l'utilisent gardent leur design)"))
    def deactivate(self, request, queryset):
        kept = queryset.filter(code="signature").count()
        if kept:
            self.message_user(
                request,
                _("Le modèle par défaut reste actif."),
                messages.WARNING,
            )
        self._bulk(request, queryset.exclude(code="signature"), _("%(n)d modèle(s) désactivé(s)."), is_active=False)

    @admin.action(permissions=("change",), description=_("Passer en premium"))
    def make_premium(self, request, queryset):
        self._bulk(request, queryset.exclude(code="signature"), _("%(n)d modèle(s) premium."), is_premium=True)

    @admin.action(permissions=("change",), description=_("Rendre gratuit"))
    def make_free(self, request, queryset):
        self._bulk(request, queryset, _("%(n)d modèle(s) gratuit(s)."), is_premium=False)


@admin.register(ProfileTheme)
class ProfileThemeAdmin(admin.ModelAdmin):
    list_display = ("profile", "theme", "hero_variant", "font_pair", "published_version", "published_at")
    list_filter = ("theme",)
    search_fields = ("profile__slug", "profile__display_name")
    list_select_related = ("profile", "theme")
    raw_id_fields = ("profile",)
    readonly_fields = ("draft", "draft_updated_at", "published_at", "published_version", "updated_at")
