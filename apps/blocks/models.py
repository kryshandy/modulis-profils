"""Content blocks of a pro page (page builder, ADR-0012). Their position lives in the theme sections."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.profiles.models import Profile

from .registry import BLOCK_TYPES


def block_image_path(instance, filename: str) -> str:
    import uuid

    return f"profiles/{instance.block.profile_id}/blocks/{uuid.uuid4().hex}.webp"


class PageBlock(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="blocks")
    kind = models.CharField(_("type"), max_length=20, choices=[(k, t.label) for k, t in BLOCK_TYPES.items()])
    # Validated by apps.blocks.services.clean_data against the registry: plain text only.
    data = models.JSONField(_("contenu"), default=dict, blank=True)
    style = models.JSONField(_("style"), default=dict, blank=True)  # whitelisted enums only
    # Hidden by the Modulis team (moderation): never rendered, the pro cannot show it again.
    moderated = models.BooleanField(_("masqué par la modération"), default=False, db_index=True)
    moderation_note = models.CharField(_("motif de modération"), max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("bloc de page")
        verbose_name_plural = _("blocs de page")
        ordering = ["profile", "pk"]

    def __str__(self) -> str:
        title = (self.data or {}).get("title") or ""
        return f"{self.get_kind_display()}{' — ' + title if title else ''}"

    @property
    def key(self) -> str:
        """Key of this block in the theme sections list (apps.themes.services.normalize_sections)."""
        return f"b{self.pk}"

    @property
    def anchor(self) -> str:
        return f"bloc-{self.pk}"

    @property
    def block_type(self):
        return BLOCK_TYPES.get(self.kind)


class BlockImage(models.Model):
    block = models.ForeignKey(PageBlock, on_delete=models.CASCADE, related_name="images")
    slot = models.CharField(max_length=20)  # "image", "before_0", "after_0"…
    image = models.ImageField(upload_to=block_image_path)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("image de bloc")
        verbose_name_plural = _("images de bloc")
        constraints = [models.UniqueConstraint(fields=["block", "slot"], name="blockimage_slot_unique")]

    def __str__(self) -> str:
        return f"{self.block_id}:{self.slot}"
