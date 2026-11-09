"""Plans, subscriptions and payments (Point d'équipe §3). Expiry = back to free, never deletion."""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Country
from apps.profiles.models import Profile


class Plan(models.Model):
    class Code(models.TextChoices):
        FREE = "free", _("Gratuit")
        ESSENTIEL = "essentiel", _("Essentiel")
        PRO = "pro", _("Pro")
        TEAM = "team", _("Équipe")

    code = models.CharField(max_length=12, choices=Code.choices, unique=True)
    name = models.CharField(max_length=40)
    description = models.TextField(blank=True)
    # Entitlements, e.g. {"hide_branding": true, "verified_badge": true, "advanced_stats": true,
    # "max_profiles": 1, "reviews": false, "quotes": false, "featured": false, "free_cards": 0}
    entitlements = models.JSONField(default=dict)
    is_public = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("offre")
        verbose_name_plural = _("offres")
        ordering = ["order"]

    def __str__(self) -> str:
        return self.name


class PlanPrice(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="prices")
    country = models.ForeignKey(Country, on_delete=models.PROTECT)
    amount = models.PositiveIntegerField(_("montant annuel"))
    currency = models.CharField(max_length=3, default="XAF")

    class Meta:
        verbose_name = _("prix")
        verbose_name_plural = _("prix")
        constraints = [models.UniqueConstraint(fields=["plan", "country"], name="planprice_unique")]

    def __str__(self) -> str:
        return f"{self.plan} — {self.amount} {self.currency}"


class Subscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        EXPIRED = "expired", _("Expirée")
        CANCELLED = "cancelled", _("Annulée")

    class Source(models.TextChoices):
        PAYMENT = "payment", _("Paiement en ligne")
        MANUAL = "manual", _("Encaissement manuel (agent / bureau)")
        REFERRAL = "referral", _("Récompense de parrainage")
        GIFT = "gift", _("Offert")

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("abonnement")
        verbose_name_plural = _("abonnements")
        ordering = ["-ends_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="sub_dates_ok"),
        ]

    def __str__(self) -> str:
        return f"{self.profile} — {self.plan} → {self.ends_at:%d/%m/%Y}"


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        SUCCEEDED = "succeeded", _("Réussi")
        FAILED = "failed", _("Échoué")
        REFUNDED = "refunded", _("Remboursé")

    reference = models.CharField(max_length=40, unique=True)
    provider = models.CharField(max_length=30)  # "manual", then the Mobile Money aggregator
    provider_reference = models.CharField(max_length=80, blank=True, db_index=True)
    profile = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="payments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, null=True, blank=True)
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="XAF")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    subscription = models.OneToOneField(Subscription, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("paiement")
        verbose_name_plural = _("paiements")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reference} {self.amount} {self.currency} [{self.status}]"
