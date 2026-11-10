from django.db import models
from django.utils.translation import gettext_lazy as _


class IndexingQueue(models.Model):
    """URLs waiting to be notified to search engines (debounced batch, see docs/etudes/kliz.md)."""

    url = models.URLField(max_length=300, unique=True)
    queued_at = models.DateTimeField(auto_now=True)
    not_before = models.DateTimeField(
        _("pas avant"), null=True, blank=True, db_index=True, help_text=_("Nouvelle tentative (Retry-After).")
    )

    class Meta:
        verbose_name = _("URL à notifier")
        verbose_name_plural = _("file d'indexation")

    def __str__(self) -> str:
        return self.url


class IndexingLog(models.Model):
    """One row per kliz NotificationResult (on_result hook)."""

    provider = models.CharField(max_length=60)
    success = models.BooleanField()
    url_count = models.PositiveIntegerField(default=1)
    sample_url = models.URLField(max_length=300, blank=True)
    urls = models.JSONField(_("URL du lot"), default=list, blank=True, help_text=_("10 000 au maximum."))
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("notification d'indexation")
        verbose_name_plural = _("journal d'indexation")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.provider} {'OK' if self.success else 'ÉCHEC'} ({self.url_count})"
