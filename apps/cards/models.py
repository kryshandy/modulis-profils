"""NFC cards and QR codes with permanent identifiers (plan §4.3, ADR-0003, ADR-0005)."""

from django.conf import settings
from django.db import models
from django.db.models.functions import Upper
from django.utils.translation import gettext_lazy as _

from apps.profiles.models import Profile


class CardBatch(models.Model):
    class Kind(models.TextChoices):
        STANDARD = "standard", _("Carte NFC standard")
        CUSTOM = "custom", _("Carte NFC personnalisée")
        STICKER = "sticker", _("Sticker QR vitrine")
        PLATE = "plate", _("Plaque NFC de comptoir")

    reference = models.CharField(_("référence du lot"), max_length=40, unique=True)
    kind = models.CharField(_("type"), max_length=10, choices=Kind.choices, default=Kind.STANDARD)
    quantity = models.PositiveIntegerField(_("quantité"))
    supplier = models.CharField(_("fournisseur"), max_length=120, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    exported_at = models.DateTimeField(_("exporté pour l'imprimeur le"), null=True, blank=True)
    received_at = models.DateTimeField(_("reçu et contrôlé le"), null=True, blank=True)
    nfc_lock_checked = models.BooleanField(_("verrouillage NFC contrôlé"), default=False)

    class Meta:
        verbose_name = _("lot de cartes")
        verbose_name_plural = _("lots de cartes")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reference} ({self.quantity})"


class Card(models.Model):
    class Status(models.TextChoices):
        STOCK = "stock", _("En stock")
        SOLD = "sold", _("Vendue")
        ACTIVE = "active", _("Activée")
        DISABLED = "disabled", _("Désactivée")

    class DisabledReason(models.TextChoices):
        LOST = "lost", _("Perdue")
        REPLACED = "replaced", _("Remplacée")
        FRAUD = "fraud", _("Fraude")
        PROFILE_DELETED = "profile_deleted", _("Profil supprimé")
        OTHER = "other", _("Autre")

    public_code = models.CharField(_("code public"), max_length=12, unique=True)
    activation_code_hash = models.CharField(_("empreinte du code d'activation"), max_length=128)
    batch = models.ForeignKey(CardBatch, on_delete=models.PROTECT, related_name="cards")
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.STOCK, db_index=True)
    profile = models.ForeignKey(
        Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name="cards", verbose_name=_("profil lié")
    )
    label = models.CharField(_("nom donné par le pro"), max_length=60, blank=True)
    sold_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.CharField(max_length=20, choices=DisabledReason.choices, blank=True)
    scan_count = models.PositiveIntegerField(default=0)
    last_scan_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("carte")
        verbose_name_plural = _("cartes")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(status="active") | models.Q(profile__isnull=False),
                name="active_card_has_profile",
            ),
            models.CheckConstraint(
                condition=models.Q(public_code=Upper("public_code")),
                name="card_code_uppercase",
            ),
        ]

    def __str__(self) -> str:
        return self.public_code

    @property
    def url(self) -> str:
        """The URL printed in the QR and written in the NFC chip. Format frozen forever."""
        return f"{settings.SITE_URL}/c/{self.public_code}"


class CardActivationAttempt(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="activation_attempts")
    ip_hash = models.CharField(max_length=32, db_index=True)
    success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("tentative d'activation")
        verbose_name_plural = _("tentatives d'activation")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.card_id} {'OK' if self.success else 'KO'} {self.created_at:%Y-%m-%d %H:%M}"
