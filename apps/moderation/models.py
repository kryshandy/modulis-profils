from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.profiles.models import Profile


class Report(models.Model):
    class Reason(models.TextChoices):
        SCAM = "scam", _("Arnaque / escroquerie")
        IMPERSONATION = "impersonation", _("Usurpation d'identité")
        INAPPROPRIATE = "inappropriate", _("Contenu choquant")
        SPAM = "spam", _("Publicité / spam")
        WRONG_INFO = "wrong_info", _("Informations fausses")
        OTHER = "other", _("Autre")

    class Status(models.TextChoices):
        OPEN = "open", _("À traiter")
        DISMISSED = "dismissed", _("Classé sans suite")
        ACTIONED = "actioned", _("Mesure prise")

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(_("motif"), max_length=20, choices=Reason.choices)
    message = models.TextField(_("message"), max_length=1000, blank=True)
    reporter_contact = models.CharField(_("contact du signaleur"), max_length=120, blank=True)
    reporter_ip_hash = models.CharField(max_length=32, blank=True)
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    handled_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(_("note de traitement"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("signalement")
        verbose_name_plural = _("signalements")
        ordering = ["status", "-created_at"]

    def __str__(self) -> str:
        return f"{self.get_reason_display()} — {self.profile}"
