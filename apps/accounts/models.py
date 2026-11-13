"""Accounts: one verified phone number = one account (ADR-0004)."""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Country


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone: str, password: str | None = None, **extra):
        if not phone:
            raise ValueError("phone is required")
        user = self.model(phone=phone, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()  # pros log in with an SMS code, never a password
        user.save(using=self._db)
        return user

    def create_superuser(self, phone: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not password:
            raise ValueError("staff accounts need a password")
        return self.create_user(phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Platform account. Pros authenticate by SMS OTP; staff use a password (+ 2FA later)."""

    phone = models.CharField(_("téléphone (E.164)"), max_length=16, unique=True)
    phone_verified_at = models.DateTimeField(_("téléphone vérifié le"), null=True, blank=True)
    email = models.EmailField(_("email"), blank=True)
    full_name = models.CharField(_("nom complet"), max_length=120, blank=True)
    country = models.ForeignKey(Country, on_delete=models.PROTECT, null=True, blank=True)
    is_staff = models.BooleanField(_("équipe Modulis"), default=False)
    is_active = models.BooleanField(_("actif"), default=True)
    is_field_agent = models.BooleanField(_("agent terrain"), default=False)
    date_joined = models.DateTimeField(_("inscrit le"), default=timezone.now)
    last_seen_at = models.DateTimeField(_("vu pour la dernière fois"), null=True, blank=True)
    # Version of the CGU + privacy policy accepted (apps.legal.conf.LEGAL_VERSION) and when.
    terms_version = models.CharField(_("version des CGU acceptée"), max_length=10, blank=True)
    terms_accepted_at = models.DateTimeField(_("CGU acceptées le"), null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        ordering = ["-date_joined"]
        constraints = [
            models.CheckConstraint(condition=models.Q(phone__startswith="+"), name="user_phone_e164"),
        ]

    def __str__(self) -> str:
        return self.full_name or self.phone


class OTPChallenge(models.Model):
    """A one-time code sent by WhatsApp or SMS (ADR-0009). Only an HMAC of the code is stored.

    For a client-side channel (Firebase), the provider holds the code: the challenge has no HMAC and
    only records that our checks passed (limits, whitelist, blocked numbers) before the send.
    """

    class Purpose(models.TextChoices):
        LOGIN = "login", _("Connexion / inscription")
        CARD_ACTIVATION = "card", _("Activation de carte")
        PHONE_CHANGE = "phone_change", _("Changement de numéro")

    phone = models.CharField(max_length=16, db_index=True)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    code_hmac = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip_hash = models.CharField(max_length=32, blank=True, db_index=True)
    channel = models.CharField(_("canal"), max_length=20, blank=True, default="")

    class Meta:
        verbose_name = _("code à usage unique")
        verbose_name_plural = _("codes à usage unique")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.phone} ({self.get_purpose_display()})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at
