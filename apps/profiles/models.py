"""Professional profiles: the public pages at /<slug> (plan §3.3, §4)."""

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.core.models import City, TimeStampedModel, Trade


def profile_photo_path(instance: "Profile", filename: str) -> str:
    return f"profiles/{instance.pk or 'new'}/photo/{filename}"


def media_path(instance: "ProfileMedia", filename: str) -> str:
    return f"profiles/{instance.profile_id}/gallery/{filename}"


class Profile(TimeStampedModel):
    class Kind(models.TextChoices):
        PERSON = "person", _("Personne (freelance, libéral)")
        BUSINESS = "business", _("Entreprise / commerce / atelier")

    class Visibility(models.TextChoices):
        PUBLIC = "public", _("Publique")
        PRIVATE = "private", _("Privée (visible seulement par toi)")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        SUSPENDED = "suspended", _("Suspendue (modération)")
        DELETED = "deleted", _("Supprimée")

    class Language(models.TextChoices):
        FR = "fr", _("Français")
        EN = "en", _("English")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profiles")
    slug = models.SlugField(_("adresse"), max_length=50, unique=True)
    display_name = models.CharField(_("nom affiché"), max_length=80)
    kind = models.CharField(_("type"), max_length=10, choices=Kind.choices, default=Kind.PERSON)
    is_feminine = models.BooleanField(_("intitulé au féminin"), default=False)
    trade = models.ForeignKey(Trade, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("métier"))
    custom_title = models.CharField(_("intitulé personnalisé"), max_length=80, blank=True)
    city = models.ForeignKey(City, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("ville"))
    district = models.CharField(_("quartier"), max_length=80, blank=True)
    service_area = models.CharField(_("zone d'intervention"), max_length=160, blank=True)
    language = models.CharField(_("langue"), max_length=2, choices=Language.choices, default=Language.FR)
    bio = models.TextField(_("présentation"), max_length=1500, blank=True)
    photo = models.ImageField(_("photo"), upload_to=profile_photo_path, blank=True)
    photo_width = models.PositiveIntegerField(default=0, editable=False)
    photo_height = models.PositiveIntegerField(default=0, editable=False)
    cover_color = models.CharField(_("couleur"), max_length=7, default="#0A7F7D")
    # Cover image chosen among the gallery photos: fills the big visual of the page (Signature slab,
    # Vitrine and Studio frames). Empty = the drawn composition (initials) or the portrait.
    cover = models.ForeignKey(
        "profiles.ProfileMedia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("image de couverture"),
    )

    # Contact (shown as action buttons)
    whatsapp = models.CharField(_("WhatsApp (E.164)"), max_length=16, blank=True)
    phone_public = models.CharField(_("téléphone affiché (E.164)"), max_length=16, blank=True)
    email_public = models.EmailField(_("email affiché"), blank=True)
    address = models.CharField(_("adresse postale"), max_length=200, blank=True)
    maps_url = models.URLField(_("lien Google Maps"), blank=True)

    # Local SEO (schema.org LocalBusiness: geo, openingHoursSpecification, priceRange).
    latitude = models.DecimalField(_("latitude"), max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(_("longitude"), max_digits=9, decimal_places=6, null=True, blank=True)
    opening_hours = models.JSONField(
        _("horaires d'ouverture"),
        default=dict,
        blank=True,
        help_text=_('ex. {"mo": [["08:00", "18:00"]], "su": []} — jour absent ou liste vide = fermé'),
    )
    price_range = models.CharField(
        _("gamme de prix"), max_length=20, blank=True, help_text=_("ex. « $$ » ou « 5 000–50 000 FCFA »")
    )

    visibility = models.CharField(_("visibilité"), max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)

    # SEO (plan §6.6) — computed by services.refresh_seo_state()
    completeness_score = models.PositiveSmallIntegerField(_("complétude"), default=0)
    is_indexable = models.BooleanField(_("indexable par Google"), default=False, db_index=True)
    bio_fingerprint = models.CharField(max_length=16, blank=True, db_index=True)
    content_updated_at = models.DateTimeField(_("contenu modifié le"), null=True, blank=True)

    verified_at = models.DateTimeField(_("vérifié le"), null=True, blank=True)
    onboarding_completed_at = models.DateTimeField(_("onboarding terminé le"), null=True, blank=True)
    tour_completed_at = models.DateTimeField(_("visite guidée terminée le"), null=True, blank=True)
    created_by_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_profiles",
        verbose_name=_("créé par l'agent"),
    )
    suspended_reason = models.CharField(_("motif de suspension"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("profil")
        verbose_name_plural = _("profils")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["city", "trade", "is_indexable"])]
        permissions = [
            ("grant_subscription", _("Peut offrir un abonnement depuis l'administration")),
            ("erase_profile", _("Peut effacer définitivement un profil (droit à l'effacement)")),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(slug=Lower("slug")), name="profile_slug_lowercase"),
            models.CheckConstraint(
                condition=models.Q(latitude__isnull=True) | models.Q(latitude__gte=-90, latitude__lte=90),
                name="profile_latitude_range",
            ),
            models.CheckConstraint(
                condition=models.Q(longitude__isnull=True) | models.Q(longitude__gte=-180, longitude__lte=180),
                name="profile_longitude_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.slug})"

    def get_absolute_url(self) -> str:
        return f"/{self.slug}"

    @property
    def absolute_url(self) -> str:
        return f"{settings.SITE_URL}/{self.slug}"

    @property
    def title(self) -> str:
        """Job title shown under the name: custom title, else trade label."""
        if self.custom_title:
            return self.custom_title
        if self.trade:
            return self.trade.label(feminine=self.is_feminine, language=self.language)
        return ""

    @property
    def is_publicly_visible(self) -> bool:
        return self.status == self.Status.ACTIVE and self.visibility == self.Visibility.PUBLIC

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None


class SlugRegistry(models.Model):
    """Single source of truth for every first-level URL segment (review item #6).

    current  -> the live slug of a profile (200)
    old      -> a previous slug (301 to current, forever, never re-assigned)
    reserved -> system routes, trades, cities, brands (never assignable)
    erased   -> profile deleted (410); stores a hash, not the person's name
    """

    class Kind(models.TextChoices):
        CURRENT = "current", _("Actuel")
        OLD = "old", _("Ancien (redirection 301)")
        RESERVED = "reserved", _("Réservé")
        ERASED = "erased", _("Effacé (410)")

    slug = models.CharField(max_length=64, primary_key=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, db_index=True)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, null=True, blank=True, related_name="slugs")
    reason = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(_("devenue ancienne le"), null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = _("adresse réservée / historique")
        verbose_name_plural = _("registre des adresses")
        constraints = [
            models.CheckConstraint(condition=models.Q(slug=Lower("slug")), name="slug_lowercase"),
            models.CheckConstraint(
                condition=(
                    models.Q(kind__in=["current", "old"], profile__isnull=False)
                    | models.Q(kind__in=["reserved", "erased"], profile__isnull=True)
                ),
                name="slug_profile_consistency",
            ),
            models.CheckConstraint(
                condition=models.Q(kind="old") | models.Q(retired_at__isnull=True),
                name="slug_retired_only_when_old",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.slug} [{self.kind}]"


class ProfileLink(models.Model):
    class Kind(models.TextChoices):
        WEBSITE = "website", _("Site web")
        FACEBOOK = "facebook", "Facebook"
        INSTAGRAM = "instagram", "Instagram"
        TIKTOK = "tiktok", "TikTok"
        LINKEDIN = "linkedin", "LinkedIn"
        YOUTUBE = "youtube", "YouTube"
        X = "x", "X (Twitter)"
        OTHER = "other", _("Autre")

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="links")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    url = models.URLField(max_length=300)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("lien")
        verbose_name_plural = _("liens")

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.url}"


class ProfileService(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="services")
    title = models.CharField(_("prestation"), max_length=100)
    description = models.CharField(_("détail"), max_length=300, blank=True)
    price_label = models.CharField(
        _("prix indicatif"), max_length=60, blank=True, help_text=_("ex. « dès 5 000 FCFA »")
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("prestation")
        verbose_name_plural = _("prestations")

    def __str__(self) -> str:
        return self.title


class ProfileMedia(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="media")
    image = models.ImageField(upload_to=media_path)
    caption = models.CharField(_("légende"), max_length=140, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("photo de réalisation")
        verbose_name_plural = _("galerie")

    def __str__(self) -> str:
        return self.caption or f"photo {self.pk}"
