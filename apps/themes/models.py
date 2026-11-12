"""Site templates ("modèles") a professional can activate, fill and customise for their public page.

Theme         = a ready-made professional design (layout + palette + fonts + section order), seeded by a
                data migration and managed from the admin (activate, premium, order).
ProfileTheme  = the choice and customisations of ONE profile: the live settings (rendered on /<slug>)
                and a draft (rendered in the private preview) copied to live by "Valider et publier".

Every write goes through apps.themes.services (validation, contrast, publication, indexing).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.profiles.models import Profile


class Theme(models.Model):
    class Category(models.TextChoices):
        ARTISAN_BTP = "artisan_btp", _("Artisans & BTP")
        BEAUTE = "beaute", _("Beauté & bien-être")
        RESTAURATION = "restauration", _("Restauration")
        MODE = "mode", _("Mode & couture")
        TECH_FREELANCE = "tech_freelance", _("Tech & freelance")
        SANTE = "sante", _("Santé")
        CONSEIL_JURIDIQUE = "conseil_juridique", _("Conseil & juridique")
        COMMERCE = "commerce", _("Commerce & boutique")
        EVENEMENTIEL_PHOTO = "evenementiel_photo", _("Événementiel & photo")
        EDUCATION = "education", _("Éducation & formation")
        UNIVERSEL = "universel", _("Universel")

    class Layout(models.TextChoices):
        # Keys are stable (stored in ProfileTheme); labels name the 2026 art directions.
        SPLIT_PHOTO = "split_photo", _("Studio — colonne image fixe")
        COVER_COLOR = "cover_color", _("Signature — typographie XXL")
        CENTERED = "centered", _("Bento — grille de tuiles")
        CARD = "card", _("Carte — luxe épuré")
        EDITORIAL = "editorial", _("Éditorial — serif magazine")
        MAGAZINE = "magazine", _("Vitrine — grande image")

    code = models.SlugField(_("code"), max_length=40, unique=True)
    name = models.CharField(_("nom"), max_length=60)
    category = models.CharField(_("catégorie"), max_length=24, choices=Category.choices, db_index=True)
    description = models.CharField(_("description"), max_length=240, blank=True)
    layout = models.CharField(_("mise en page"), max_length=16, choices=Layout.choices, default=Layout.COVER_COLOR)
    palette = models.JSONField(
        _("palette par défaut"),
        default=dict,
        help_text=_("Clés : primary, accent, background, surface, text (couleurs #RRGGBB)."),
    )
    palette_presets = models.JSONField(
        _("palettes proposées"), default=list, blank=True, help_text=_("Liste de palettes {name, primary, …}.")
    )
    font_pair = models.CharField(_("typographie"), max_length=20, default="system")
    corners = models.CharField(_("angles"), max_length=8, default="rounded")
    sections = models.JSONField(_("ordre des sections"), default=list, blank=True)
    cta_label = models.CharField(_("bouton principal"), max_length=40, blank=True)
    is_active = models.BooleanField(_("actif"), default=True, db_index=True)
    is_premium = models.BooleanField(_("premium"), default=False)
    order = models.PositiveSmallIntegerField(_("ordre"), default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("modèle de site")
        verbose_name_plural = _("modèles de site")
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name


class ProfileTheme(models.Model):
    class Corners(models.TextChoices):
        ROUNDED = "rounded", _("Arrondis")
        SOFT = "soft", _("Légers")
        SHARP = "sharp", _("Droits")

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="theme_settings")
    theme = models.ForeignKey(Theme, on_delete=models.PROTECT, related_name="profile_themes", verbose_name=_("modèle"))
    palette = models.JSONField(_("couleurs personnalisées"), default=dict, blank=True)
    font_pair = models.CharField(_("typographie"), max_length=20, blank=True)
    corners = models.CharField(_("angles"), max_length=8, choices=Corners.choices, blank=True)
    hero_variant = models.CharField(_("en-tête"), max_length=16, choices=Theme.Layout.choices, blank=True)
    cta_label = models.CharField(_("texte du bouton principal"), max_length=40, blank=True)
    sections = models.JSONField(
        _("sections"), default=list, blank=True, help_text=_('[{"key": "services", "visible": true}, …]')
    )
    draft = models.JSONField(_("brouillon"), default=dict, blank=True)
    draft_updated_at = models.DateTimeField(_("brouillon modifié le"), null=True, blank=True)
    published_at = models.DateTimeField(_("publié le"), null=True, blank=True)
    published_version = models.PositiveIntegerField(_("version publiée"), default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("modèle d'une page")
        verbose_name_plural = _("modèles des pages")

    def __str__(self) -> str:
        return f"{self.profile} — {self.theme}"
