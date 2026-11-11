from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import BaseUserCreationForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Exists, OuterRef
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.platform import services as platform
from apps.platform.models import BlockedPhone
from apps.profiles.models import Profile
from apps.security import services as security

from . import services
from .models import OTPChallenge, User

PRIVILEGE_FIELDS = ("is_staff", "is_superuser", "groups", "user_permissions")


def _clean_phone(raw: str) -> str:
    try:
        phone = services.normalize_phone(raw)
    except services.OTPError as exc:
        raise forms.ValidationError(str(exc)) from exc
    if User.objects.filter(phone=phone).exists():
        raise forms.ValidationError(_("Un compte existe déjà avec ce numéro."))
    return phone


class StaffCreationForm(BaseUserCreationForm):
    """Admin "add user" creates STAFF accounts (phone + password). Pros sign up by SMS code."""

    class Meta:
        model = User
        fields = ("phone", "full_name", "email")

    def clean_phone(self):
        return _clean_phone(self.cleaned_data.get("phone", ""))

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        if commit:
            user.save()
            self.save_m2m()
        return user


class UserChangeForm(BaseUserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class ProfileInline(admin.TabularInline):
    model = Profile
    fk_name = "user"
    fields = ("display_name", "public_link", "trade", "city", "status", "visibility", "completeness_score")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    @admin.display(description=_("adresse"))
    def public_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">/{}</a>', obj.get_absolute_url(), obj.slug)

    def has_add_permission(self, request, obj=None):
        return False


class BlockedFilter(admin.SimpleListFilter):
    title = _("numéro bloqué")
    parameter_name = "blocked"

    def lookups(self, request, model_admin):
        return [("yes", _("Oui")), ("no", _("Non"))]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(phone__in=BlockedPhone.objects.values("phone"))
        if self.value() == "no":
            return queryset.exclude(phone__in=BlockedPhone.objects.values("phone"))
        return queryset


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = StaffCreationForm
    list_display = (
        "phone",
        "full_name",
        "profiles_count",
        "is_verified",
        "is_staff",
        "two_factor",
        "is_field_agent",
        "is_active",
        "blocked",
        "last_seen_at",
        "date_joined",
    )
    list_filter = (
        "is_active",
        BlockedFilter,
        "is_staff",
        "is_superuser",
        "is_field_agent",
        "country",
        "last_seen_at",
        "date_joined",
    )
    actions = (
        "deactivate_accounts",
        "reactivate_accounts",
        "logout_everywhere",
        "block_phones",
        "unblock_phones",
        "reset_two_factor",
    )
    search_fields = ("phone", "full_name", "email", "profiles__slug")
    ordering = ("-date_joined",)
    readonly_fields = ("date_joined", "last_seen_at", "last_login", "phone_verified_at")
    inlines = [ProfileInline]
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        (_("Identité"), {"fields": ("full_name", "email", "country")}),
        (_("Statut"), {"fields": ("is_active", "phone_verified_at", "is_field_agent")}),
        (
            _("Équipe Modulis"),
            {"classes": ("collapse",), "fields": ("is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Dates"), {"fields": ("date_joined", "last_seen_at", "last_login")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "description": _(
                    "Ce formulaire crée un compte de l'équipe Modulis (connexion par mot de passe). "
                    "Les professionnels créent leur compte eux-mêmes par SMS."
                ),
                "fields": ("phone", "full_name", "email", "password1", "password2"),
            },
        ),
    )

    def get_inlines(self, request, obj):
        return self.inlines if obj is not None else []  # no inline on the "add staff" form

    def get_queryset(self, request):
        blocked = BlockedPhone.objects.filter(phone=OuterRef("phone"))
        return (
            super()
            .get_queryset(request)
            .annotate(
                _profiles=Count("profiles", distinct=True),
                _blocked=Exists(blocked),
                _two_factor=Exists(TOTPDevice.objects.filter(user=OuterRef("pk"), confirmed=True)),
            )
        )

    def has_change_permission(self, request, obj=None):
        """Only a superuser may edit a superuser (no privilege escalation through the change form)."""
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        """Privilege fields: only a superuser edits them, and never on their own account.

        A staff member holding accounts.change_user must not be able to tick is_superuser or grant
        himself permissions; a superuser must not demote or lock himself out by accident.
        """
        fields = tuple(super().get_readonly_fields(request, obj))
        if obj is not None and (not request.user.is_superuser or obj.pk == request.user.pk):
            fields += tuple(f for f in PRIVILEGE_FIELDS if f not in fields)
        return fields

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and "is_active" in form.changed_data:
            if not obj.is_active:
                platform.terminate_sessions(obj)
            platform.audit(request.user, "user.activate" if obj.is_active else "user.deactivate", obj.phone)
        if change and set(PRIVILEGE_FIELDS) & set(form.changed_data):
            platform.audit(request.user, "user.permissions", obj.phone, fields=sorted(form.changed_data))

    def delete_model(self, request, obj):
        phone, pk = obj.phone, obj.pk
        super().delete_model(request, obj)
        platform.audit(request.user, "user.delete", phone, user_id=pk)

    def delete_queryset(self, request, queryset):
        doomed = list(queryset.values_list("pk", "phone"))
        super().delete_queryset(request, queryset)
        for pk, phone in doomed:
            platform.audit(request.user, "user.delete", phone, user_id=pk)

    @admin.display(description=_("2FA"), boolean=True, ordering="_two_factor")
    def two_factor(self, obj):
        """Staff only: confirmed TOTP device (pros never use 2FA, they log in by SMS code)."""
        return bool(getattr(obj, "_two_factor", False)) if obj.is_staff else None

    @admin.display(description=_("numéro bloqué"), boolean=True, ordering="_blocked")
    def blocked(self, obj):
        return bool(getattr(obj, "_blocked", False))

    # Account actions (audited in apps.platform) -------------------------------------------

    def has_block_permission(self, request):
        return request.user.has_perm("platform_settings.add_blockedphone") and request.user.has_perm(
            "accounts.change_user"
        )

    def has_unblock_permission(self, request):
        return request.user.has_perm("platform_settings.delete_blockedphone") and request.user.has_perm(
            "accounts.change_user"
        )

    def has_reset_2fa_permission(self, request):
        return request.user.is_superuser

    def _targets(self, request, queryset):
        """Accounts the current admin may act on: never itself, never a superuser unless superuser."""
        allowed, skipped = [], 0
        for user in queryset:
            if user.pk == request.user.pk or (user.is_superuser and not request.user.is_superuser):
                skipped += 1
            else:
                allowed.append(user)
        if skipped:
            self.message_user(
                request,
                _("%(n)d compte(s) ignoré(s) : ton propre compte ou un super-administrateur.") % {"n": skipped},
                messages.WARNING,
            )
        return allowed

    @admin.action(permissions=["change"], description=_("Désactiver (et déconnecter)"))
    def deactivate_accounts(self, request, queryset):
        users = self._targets(request, queryset)
        platform.set_users_active(users, False, actor=request.user)
        self.message_user(request, _("%(n)d compte(s) désactivé(s).") % {"n": len(users)}, messages.SUCCESS)

    @admin.action(permissions=["change"], description=_("Réactiver"))
    def reactivate_accounts(self, request, queryset):
        users = self._targets(request, queryset)
        platform.set_users_active(users, True, actor=request.user)
        self.message_user(request, _("%(n)d compte(s) réactivé(s).") % {"n": len(users)}, messages.SUCCESS)

    @admin.action(permissions=["change"], description=_("Déconnecter de tous les appareils"))
    def logout_everywhere(self, request, queryset):
        total = platform.logout_users_everywhere(self._targets(request, queryset), actor=request.user)
        self.message_user(request, _("%(n)d session(s) fermée(s).") % {"n": total}, messages.SUCCESS)

    @admin.action(permissions=["block"], description=_("Bloquer le numéro (désactive et déconnecte)"))
    def block_phones(self, request, queryset):
        users = self._targets(request, queryset)
        reason = str(_("Bloqué depuis l'administration par %(who)s") % {"who": request.user})
        done = 0
        for user in users:
            try:
                platform.block_phone(user.phone, reason=reason, actor=request.user)
            except PermissionDenied as exc:
                self.message_user(request, f"{user.phone} : {exc}", messages.ERROR)
            else:
                done += 1
        self.message_user(request, _("%(n)d numéro(s) bloqué(s).") % {"n": done}, messages.SUCCESS)

    @admin.action(permissions=["unblock"], description=_("Débloquer le numéro (et réactiver)"))
    def unblock_phones(self, request, queryset):
        users = self._targets(request, queryset)
        count = sum(platform.unblock_phone(user.phone, actor=request.user) for user in users)
        self.message_user(request, _("%(n)d numéro(s) débloqué(s).") % {"n": count}, messages.SUCCESS)

    @admin.action(permissions=["reset_2fa"], description=_("Réinitialiser la double authentification"))
    def reset_two_factor(self, request, queryset):
        """Lost phone: delete the 2FA devices and close the sessions; next login forces enrollment."""
        done = 0
        for user in queryset:
            if user.pk == request.user.pk:
                self.message_user(
                    request,
                    _("Ta propre double authentification se réinitialise par un autre super-administrateur."),
                    messages.WARNING,
                )
                continue
            try:
                security.reset_two_factor(user, actor=request.user)
            except PermissionDenied:
                continue
            done += 1
        self.message_user(
            request,
            _("Double authentification réinitialisée pour %(n)d compte(s) : nouveau QR code à la prochaine connexion.")
            % {"n": done},
            messages.SUCCESS,
        )

    @admin.display(description=_("pages"), ordering="_profiles")
    def profiles_count(self, obj):
        count = getattr(obj, "_profiles", 0)
        if not count:
            return 0
        url = reverse("admin:profiles_profile_changelist") + f"?user__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, count)

    @admin.display(description=_("vérifié"), boolean=True, ordering="phone_verified_at")
    def is_verified(self, obj):
        return obj.phone_verified_at is not None


@admin.register(OTPChallenge)
class OTPChallengeAdmin(admin.ModelAdmin):
    """Read-only journal (abuse investigation). Codes are stored as HMAC only."""

    list_display = ("created_at", "phone", "purpose", "attempts", "consumed_at", "expires_at")
    list_filter = ("purpose", "created_at")
    search_fields = ("phone", "ip_hash")
    date_hierarchy = "created_at"
    exclude = ("code_hmac",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
