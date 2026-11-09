from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import BaseUserCreationForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.profiles.models import Profile

from . import services
from .models import OTPChallenge, User


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
        "is_field_agent",
        "is_active",
        "last_seen_at",
        "date_joined",
    )
    list_filter = ("is_staff", "is_superuser", "is_field_agent", "is_active", "country", "date_joined")
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
        from django.db.models import Count

        return super().get_queryset(request).annotate(_profiles=Count("profiles", distinct=True))

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
