"""Reference data admin. A trade or city slug must never steal a slug already owned by a profile
(plan §3.3): the ModelForms check the SlugRegistry before saving (the post_save signal then reserves it)."""

from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.profiles.models import SlugRegistry
from apps.profiles.services import slug_hash

from .models import City, Country, Trade


def slug_owned_by_profile(slug: str) -> bool:
    """True if a profile uses (or used) this slug: current, old (301) or erased (410)."""
    slug = (slug or "").lower()
    return (
        SlugRegistry.objects.filter(slug__in=[slug, slug_hash(slug)]).exclude(kind=SlugRegistry.Kind.RESERVED).exists()
    )


def _check_slug(form: forms.ModelForm, field: str) -> None:
    value = form.cleaned_data.get(field)
    if not value:
        return
    if form.instance.pk and getattr(form.instance, field) == value:
        return  # unchanged
    if slug_owned_by_profile(value):
        form.add_error(
            field,
            _("L'adresse « %(slug)s » appartient déjà à une page pro : choisis un autre slug.") % {"slug": value},
        )


class TradeForm(forms.ModelForm):
    class Meta:
        model = Trade
        fields = (
            "name",
            "name_feminine",
            "name_en",
            "slug",
            "plural_slug",
            "plural_name",
            "segment",
            "schema_type",
            "is_active",
        )

    def clean(self):
        cleaned = super().clean()
        _check_slug(self, "slug")
        _check_slug(self, "plural_slug")
        return cleaned


class CityForm(forms.ModelForm):
    class Meta:
        model = City
        fields = ("country", "name", "slug", "region", "is_active")

    def clean(self):
        cleaned = super().clean()
        _check_slug(self, "slug")
        return cleaned


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "phone_prefix", "currency", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    form = CityForm
    list_display = ("name", "slug", "region", "country", "is_active")
    list_filter = ("country", "region", "is_active")
    search_fields = ("name", "slug", "region")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    form = TradeForm
    list_display = ("name", "name_feminine", "slug", "plural_slug", "segment", "schema_type", "is_active")
    list_filter = ("segment", "is_active", "schema_type")
    search_fields = ("name", "name_feminine", "name_en", "slug", "plural_slug")
    prepopulated_fields = {"slug": ("name",), "plural_slug": ("plural_name",)}
