from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Payment, Plan, PlanPrice, Subscription


def _profile_link(profile):
    url = reverse("admin:profiles_profile_change", args=[profile.pk])
    return format_html('<a href="{}">{}</a>', url, profile.slug)


class PlanPriceInline(admin.TabularInline):
    model = PlanPrice
    extra = 0


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "order", "is_public", "prices")
    list_editable = ("order", "is_public")
    inlines = [PlanPriceInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("prices")

    @admin.display(description=_("prix annuels"))
    def prices(self, obj):
        return ", ".join(f"{p.country_id} {p.amount} {p.currency}" for p in obj.prices.all()) or "—"

    def has_delete_permission(self, request, obj=None):
        return False  # plans are referenced by subscriptions and payments


@admin.register(PlanPrice)
class PlanPriceAdmin(admin.ModelAdmin):
    list_display = ("plan", "country", "amount", "currency")
    list_filter = ("plan", "country")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("profile_link", "plan", "starts_at", "ends_at", "status", "source", "created_by")
    list_filter = ("status", "plan", "source", "ends_at")
    search_fields = ("profile__slug", "profile__display_name", "profile__user__phone", "note")
    list_select_related = ("profile", "plan", "created_by")
    raw_id_fields = ("profile",)
    readonly_fields = ("created_by", "created_at")
    date_hierarchy = "ends_at"
    actions = ("expire_now",)

    @admin.display(description=_("profil"), ordering="profile__slug")
    def profile_link(self, obj):
        return _profile_link(obj.profile)

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Expirer maintenant (retour au gratuit)"))
    def expire_now(self, request, queryset):
        count = queryset.filter(status=Subscription.Status.ACTIVE).update(status=Subscription.Status.EXPIRED)
        self.message_user(request, _("%(n)d abonnement(s) expiré(s).") % {"n": count}, messages.SUCCESS)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Read-mostly: payments are written by providers' webhooks, never by hand."""

    list_display = ("reference", "created_at", "profile_link", "plan", "amount", "currency", "provider", "status")
    list_filter = ("status", "provider", "plan", "created_at")
    search_fields = ("reference", "provider_reference", "profile__slug", "profile__user__phone")
    list_select_related = ("profile", "plan")
    date_hierarchy = "created_at"
    readonly_fields = (
        "reference",
        "provider",
        "provider_reference",
        "profile",
        "plan",
        "amount",
        "currency",
        "status",
        "raw_payload",
        "subscription",
        "created_at",
        "updated_at",
    )

    @admin.display(description=_("profil"), ordering="profile__slug")
    def profile_link(self, obj):
        return _profile_link(obj.profile)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
