"""Reference data shared by every app: countries, cities and trades (ADR-0006)."""

from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        abstract = True


class Country(models.Model):
    code = models.CharField(_("code ISO"), max_length=2, primary_key=True)
    name = models.CharField(_("nom"), max_length=80)
    phone_prefix = models.CharField(_("indicatif"), max_length=6, help_text="+237")
    currency = models.CharField(_("devise"), max_length=3, default="XAF")
    is_active = models.BooleanField(_("ouvert"), default=False)

    class Meta:
        verbose_name = _("pays")
        verbose_name_plural = _("pays")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class City(models.Model):
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="cities")
    name = models.CharField(_("nom"), max_length=80)
    slug = models.SlugField(_("slug"), max_length=80)
    region = models.CharField(_("région"), max_length=80, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("ville")
        verbose_name_plural = _("villes")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["country", "slug"], name="city_unique_slug_per_country"),
        ]

    def __str__(self) -> str:
        return self.name


class Trade(models.Model):
    """A profession. Carries its schema.org type for structured data (plan §6.3)."""

    class Segment(models.TextChoices):
        CRAFT = "craft", _("Artisan / commerçant")
        LIBERAL = "liberal", _("Freelance / profession libérale")

    name = models.CharField(_("nom"), max_length=80, help_text=_("Masculin, ex. « Plombier »"))
    name_feminine = models.CharField(_("nom au féminin"), max_length=80, blank=True)
    name_en = models.CharField(_("nom en anglais"), max_length=80, blank=True)
    slug = models.SlugField(_("slug"), max_length=80, unique=True)
    plural_slug = models.SlugField(
        _("slug pluriel"), max_length=80, unique=True, help_text=_("Utilisé par l'annuaire : /plombiers/douala")
    )
    plural_name = models.CharField(_("nom au pluriel"), max_length=80)
    segment = models.CharField(_("segment"), max_length=10, choices=Segment.choices)
    schema_type = models.CharField(
        _("type schema.org"),
        max_length=60,
        default="LocalBusiness",
        help_text=_("Person pour les libéraux ; sinon LocalBusiness ou un sous-type (Plumber, HairSalon…)"),
    )
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("métier")
        verbose_name_plural = _("métiers")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="trade_unique_name_ci"),
        ]

    def __str__(self) -> str:
        return self.name

    def label(self, feminine: bool = False, language: str = "fr") -> str:
        if language == "en" and self.name_en:
            return self.name_en
        if feminine and self.name_feminine:
            return self.name_feminine
        return self.name
