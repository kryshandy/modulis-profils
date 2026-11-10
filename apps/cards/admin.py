"""Card back-office. Activation codes exist in clear ONLY in the CSV returned right after a batch
is generated (ADR-0005): it is streamed from memory, never written to disk, never re-exportable."""

import csv
import io

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from . import services
from .forms import GenerateBatchForm
from .models import Card, CardActivationAttempt, CardBatch


@admin.register(CardBatch)
class CardBatchAdmin(admin.ModelAdmin):
    change_list_template = "admin/cards/cardbatch/change_list.html"
    list_display = (
        "reference",
        "kind",
        "quantity",
        "supplier",
        "created_at",
        "exported_at",
        "nfc_lock_checked",
        "active_cards",
    )
    list_filter = ("kind", "nfc_lock_checked", "created_at")
    search_fields = ("reference", "supplier")
    readonly_fields = ("reference", "kind", "quantity", "created_by", "created_at", "exported_at")
    fields = (
        "reference",
        "kind",
        "quantity",
        "supplier",
        "notes",
        "created_by",
        "created_at",
        "exported_at",
        "received_at",
        "nfc_lock_checked",
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request).annotate(_active=Count("cards", filter=Q(cards__status=Card.Status.ACTIVE)))
        )

    @admin.display(description=_("cartes activées"), ordering="_active")
    def active_cards(self, obj):
        return obj._active

    def has_add_permission(self, request):
        return False  # batches are only created through "Générer un lot"

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        custom = [
            path(
                "generer/",
                self.admin_site.admin_view(self.generate_view),
                name="cards_cardbatch_generate",
            )
        ]
        return custom + super().get_urls()

    def generate_view(self, request):
        if not request.user.has_perm("cards.add_card"):
            raise PermissionDenied
        form = GenerateBatchForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            try:
                batch, pairs = services.create_batch(
                    data["reference"],
                    data["quantity"],
                    kind=data["kind"],
                    supplier=data["supplier"],
                    created_by=request.user,
                )
            except services.CardError as exc:
                form.add_error("quantity", str(exc))
            else:
                CardBatch.objects.filter(pk=batch.pk).update(exported_at=timezone.now())
                return self._csv_response(batch, pairs)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "form": form,
            "title": _("Générer un lot de cartes"),
        }
        return TemplateResponse(request, "admin/cards/cardbatch/generate.html", context)

    @staticmethod
    def _csv_response(batch, pairs):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["public_code", "url", "activation_code"])
        writer.writerows(services.batch_export_rows(pairs))
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="lot-{batch.reference}.csv"'
        response["Cache-Control"] = "no-store"
        return response


DISABLE_REASONS = {
    "lost": Card.DisabledReason.LOST,
    "replaced": Card.DisabledReason.REPLACED,
    "fraud": Card.DisabledReason.FRAUD,
}


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = (
        "public_code",
        "status",
        "batch",
        "profile_link",
        "label",
        "scan_count",
        "activated_at",
        "last_scan_at",
    )
    list_filter = ("status", "batch", "disabled_reason", "batch__kind")
    search_fields = ("public_code", "profile__slug", "profile__display_name", "profile__user__phone", "label")
    list_select_related = ("batch", "profile")
    readonly_fields = (
        "public_code",
        "url",
        "activation_code_hash",
        "batch",
        "status",
        "profile_link",
        "sold_at",
        "activated_at",
        "disabled_at",
        "disabled_reason",
        "scan_count",
        "last_scan_at",
        "created_at",
    )
    fields = (*readonly_fields[:6], "label", *readonly_fields[6:])
    actions = ("mark_sold", "disable_lost", "disable_replaced", "disable_fraud")

    @admin.display(description=_("profil lié"), ordering="profile__slug")
    def profile_link(self, obj):
        if obj.profile_id is None:
            return "—"
        url = reverse("admin:profiles_profile_change", args=[obj.profile_id])
        return format_html('<a href="{}">{}</a>', url, obj.profile.slug)

    @admin.display(description=_("URL imprimée"))
    def url(self, obj):
        return obj.url

    def has_add_permission(self, request):
        return False  # cards are only created by batch generation

    def has_delete_permission(self, request, obj=None):
        return False  # a printed code must never disappear: disable it instead

    @admin.action(permissions=["change"], description=_("Marquer comme vendues"))
    def mark_sold(self, request, queryset):
        count = sum(services.mark_sold(card) for card in queryset)
        self.message_user(request, _("%(n)d carte(s) marquée(s) comme vendue(s).") % {"n": count})

    def _disable(self, request, queryset, reason):
        count = 0
        for card in queryset.exclude(status=Card.Status.DISABLED):
            services.disable_card(card, DISABLE_REASONS[reason])
            count += 1
        self.message_user(request, _("%(n)d carte(s) désactivée(s).") % {"n": count}, messages.SUCCESS)

    @admin.action(permissions=["change"], description=_("Désactiver : perdue"))
    def disable_lost(self, request, queryset):
        self._disable(request, queryset, "lost")

    @admin.action(permissions=["change"], description=_("Désactiver : remplacée"))
    def disable_replaced(self, request, queryset):
        self._disable(request, queryset, "replaced")

    @admin.action(permissions=["change"], description=_("Désactiver : fraude"))
    def disable_fraud(self, request, queryset):
        self._disable(request, queryset, "fraud")


@admin.register(CardActivationAttempt)
class CardActivationAttemptAdmin(admin.ModelAdmin):
    list_display = ("created_at", "card", "success", "ip_hash")
    list_filter = ("success", "created_at")
    search_fields = ("card__public_code", "ip_hash")
    list_select_related = ("card",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
