"""Privacy-friendly statistics: no raw IP, daily-rotating visitor hash, bot flag (plan A9)."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.profiles.models import Profile


class Event(models.Model):
    class Kind(models.TextChoices):
        VISIT = "visit", _("Visite")
        SCAN = "scan", _("Scan carte / QR")
        CLICK_CALL = "call", _("Clic Appeler")
        CLICK_WHATSAPP = "whatsapp", _("Clic WhatsApp")
        CLICK_EMAIL = "email", _("Clic Email")
        CLICK_MAPS = "maps", _("Clic Itinéraire")
        CLICK_VCARD = "vcard", _("Contact enregistré")
        CLICK_LINK = "link", _("Clic lien")
        SHARE = "share", _("Partage")

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="events")
    card = models.ForeignKey("cards.Card", on_delete=models.SET_NULL, null=True, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    referer_domain = models.CharField(max_length=120, blank=True)
    device = models.CharField(max_length=10, blank=True)  # mobile | desktop | tablet
    is_bot = models.BooleanField(default=False)
    visitor_hash = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = _("événement")
        verbose_name_plural = _("événements")
        indexes = [models.Index(fields=["profile", "kind", "created_at"])]

    def __str__(self) -> str:
        return f"{self.kind} {self.profile_id} {self.created_at:%Y-%m-%d}"


class DailyStat(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="daily_stats")
    day = models.DateField()
    kind = models.CharField(max_length=10, choices=Event.Kind.choices)
    total = models.PositiveIntegerField(default=0)
    unique_visitors = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("statistique journalière")
        verbose_name_plural = _("statistiques journalières")
        constraints = [models.UniqueConstraint(fields=["profile", "day", "kind"], name="dailystat_unique")]

    def __str__(self) -> str:
        return f"{self.day} {self.kind} = {self.total}"
