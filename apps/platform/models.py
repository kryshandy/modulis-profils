"""Platform-wide switches managed from the admin control center ("grand admin panel").

Secrets (API tokens) never live here: they stay in environment variables. The admin only enables or
disables features; the control center shows whether each provider is configured.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class SiteSettings(models.Model):
    """Singleton (pk=1). Read through apps.platform.services.get_settings() (cached)."""

    class OtpChannel(models.TextChoices):
        WHATSAPP = "whatsapp", _("WhatsApp (API Cloud de Meta)")
        FIREBASE_SMS = "firebase_sms", _("SMS via Firebase Authentication")
        SMS_GATEWAY = "sms_gateway", _("SMS via passerelle (agrégateur)")

    # Authentication
    otp_whatsapp_enabled = models.BooleanField(_("OTP par WhatsApp"), default=True)
    otp_firebase_sms_enabled = models.BooleanField(_("OTP par SMS (Firebase)"), default=True)
    otp_sms_gateway_enabled = models.BooleanField(_("OTP par SMS (passerelle)"), default=False)
    otp_default_channel = models.CharField(
        _("canal proposé par défaut"), max_length=20, choices=OtpChannel.choices, default=OtpChannel.WHATSAPP
    )
    signups_enabled = models.BooleanField(
        _("inscriptions ouvertes"), default=True, help_text=_("Désactivé : seuls les comptes existants se connectent.")
    )
    login_enabled = models.BooleanField(_("connexion à l'espace pro"), default=True)

    # Cards & pages
    card_activation_enabled = models.BooleanField(_("activation des cartes NFC"), default=True)
    page_creation_enabled = models.BooleanField(_("création de nouvelles pages"), default=True)
    themes_enabled = models.BooleanField(_("choix des modèles de site"), default=True)
    directory_enabled = models.BooleanField(_("pages annuaire (villes, métiers)"), default=True)
    reports_enabled = models.BooleanField(_("signalements publics"), default=True)

    # SEO
    indexing_notifications_enabled = models.BooleanField(
        _("notifications d'indexation (kliz)"),
        default=True,
        help_text=_("Effectif seulement si KLIZ_ENABLED est actif dans l'environnement."),
    )
    instant_publish_enabled = models.BooleanField(
        _("publication SEO instantanée"), default=True, help_text=_("Notifie les moteurs dès la publication.")
    )

    # Maintenance
    maintenance_mode = models.BooleanField(_("mode maintenance"), default=False)
    maintenance_message = models.CharField(
        _("message de maintenance"),
        max_length=240,
        default=_("Nous améliorons la plateforme. Revenez dans un instant."),
    )
    announcement = models.CharField(
        _("annonce dans l'espace pro"), max_length=240, blank=True, help_text=_("Bandeau affiché aux pros.")
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = _("réglages de la plateforme")
        verbose_name_plural = _("réglages de la plateforme")
        permissions = [("manage_platform", _("Peut piloter la plateforme (centre de contrôle)"))]

    def __str__(self) -> str:
        return str(_("Réglages de la plateforme"))

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)
        from .services import invalidate

        invalidate()


class BlockedPhone(models.Model):
    """Phone numbers refused at login/sign-up (fraud, abuse)."""

    phone = models.CharField(_("téléphone (E.164)"), max_length=16, unique=True)
    reason = models.CharField(_("motif"), max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("numéro bloqué")
        verbose_name_plural = _("numéros bloqués")

    def __str__(self) -> str:
        return self.phone


class AuditLog(models.Model):
    """Who changed what in the control center (accountability for admin actions)."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=200, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("journal d'administration")
        verbose_name_plural = _("journal d'administration")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target}"
