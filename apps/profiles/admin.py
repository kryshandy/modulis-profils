"""Profile back-office: the platform admin manages every pro page from here.

Domain rules stay in services: slug changes go through services.change_slug (SlugRegistry),
suspension/reactivation through services.suspend_profile/reactivate_profile, SEO state is always
recomputed with services.refresh_seo_state after an edit.
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import ValidationError
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.billing import services as billing
from apps.billing.models import Plan, Subscription
from apps.cards.models import Card
from apps.seo.indexing import queue_urls

from . import services
from .models import Profile, ProfileLink, ProfileMedia, ProfileService, SlugRegistry

# --- Inlines ---------------------------------------------------------------------------------


class ProfileServiceInline(admin.TabularInline):
    model = ProfileService
    extra = 0


class ProfileLinkInline(admin.TabularInline):
    model = ProfileLink
    extra = 0


class ProfileMediaInline(admin.TabularInline):
    """Images are uploaded by the pro (Pillow re-encoding strips EXIF): admins only moderate them."""

    model = ProfileMedia
    extra = 0
    fields = ("image", "caption", "order", "width", "height")
    readonly_fields = ("image", "width", "height")

    def has_add_permission(self, request, obj=None):
        return False


class CardInline(admin.TabularInline):
    model = Card
    fields = ("card_link", "status", "label", "scan_count", "activated_at", "last_scan_at")
    readonly_fields = fields
    extra = 0
    can_delete = False

    @admin.display(description=_("carte"))
    def card_link(self, obj):
        return format_html('<a href="{}">{}</a>', reverse("admin:cards_card_change", args=[obj.pk]), obj.public_code)

    def has_add_permission(self, request, obj=None):
        return False


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    fields = ("plan", "starts_at", "ends_at", "status", "source", "created_by", "note")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


# --- Filters ---------------------------------------------------------------------------------


class VerifiedFilter(admin.SimpleListFilter):
    title = _("badge vérifié")
    parameter_name = "verified"

    def lookups(self, request, model_admin):
        return [("yes", _("Oui")), ("no", _("Non"))]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(verified_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(verified_at__isnull=True)
        return queryset


class PlanFilter(admin.SimpleListFilter):
    title = _("offre")
    parameter_name = "plan"

    def lookups(self, request, model_admin):
        return Plan.Code.choices

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        now = timezone.now()
        paying = Subscription.objects.filter(status=Subscription.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now)
        if value == Plan.Code.FREE:
            return queryset.exclude(pk__in=paying.values("profile_id"))
        return queryset.filter(pk__in=paying.filter(plan__code=value).values("profile_id"))


# --- Slug change -----------------------------------------------------------------------------


class ChangeSlugForm(forms.Form):
    new_slug = forms.CharField(label=_("Nouvelle adresse"), max_length=50)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile

    def clean_new_slug(self):
        return self.cleaned_data["new_slug"].strip().lower()


class ProfileAdminForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["opening_hours"]  # the ModelAdmin passes the real list from its fieldsets

    def clean_opening_hours(self):
        return services.normalize_opening_hours(self.cleaned_data.get("opening_hours"))


# --- Profile admin ---------------------------------------------------------------------------


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "public_link",
        "owner_phone",
        "trade",
        "city",
        "status",
        "completeness_score",
        "is_indexable",
        "verified",
        "plan",
        "created_at",
    )
    list_filter = (
        "status",
        "visibility",
        "is_indexable",
        VerifiedFilter,
        PlanFilter,
        "kind",
        "trade",
        "city",
        "created_at",
    )
    search_fields = ("slug", "display_name", "user__phone", "phone_public", "whatsapp", "email_public")
    list_select_related = ("user", "trade", "city")
    raw_id_fields = ("user", "created_by_agent")
    date_hierarchy = "created_at"
    inlines = [ProfileServiceInline, ProfileLinkInline, ProfileMediaInline, CardInline, SubscriptionInline]
    readonly_fields = (
        "slug_with_change_link",
        "photo",
        "status",
        "suspended_reason",
        "completeness_score",
        "is_indexable",
        "indexability",
        "bio_fingerprint",
        "content_updated_at",
        "verified_at",
        "current_plan",
        "photo_size",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("user", "slug_with_change_link", "display_name", "kind", "language")}),
        (_("Métier et zone"), {"fields": ("trade", "is_feminine", "custom_title", "city", "district", "service_area")}),
        (_("Présentation"), {"fields": ("bio", "photo", "photo_size", "cover_color")}),
        (_("Contact"), {"fields": ("whatsapp", "phone_public", "email_public", "address", "maps_url")}),
        (_("SEO local"), {"fields": ("latitude", "longitude", "opening_hours", "price_range")}),
        (
            _("Statut et modération"),
            {"fields": ("visibility", "status", "suspended_reason", "verified_at", "current_plan")},
        ),
        (
            _("SEO (calculé)"),
            {"fields": ("completeness_score", "is_indexable", "indexability", "bio_fingerprint", "content_updated_at")},
        ),
        (
            _("Suivi"),
            {
                "fields": (
                    "created_by_agent",
                    "onboarding_completed_at",
                    "tour_completed_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    actions = (
        "verify",
        "unverify",
        "suspend",
        "reactivate",
        "recompute_seo",
        "grant_essentiel",
        "grant_pro",
        "queue_indexing",
        "erase_permanently",
    )

    def get_form(self, request, obj=None, **kwargs):
        kwargs.setdefault("form", ProfileAdminForm)
        return super().get_form(request, obj, **kwargs)

    def get_queryset(self, request):
        """Current plan annotated in SQL (one subquery instead of one query per row)."""
        now = timezone.now()
        current_plan = (
            Subscription.objects.filter(
                profile=OuterRef("pk"), status=Subscription.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now
            )
            .order_by("-ends_at")
            .values("plan__code")[:1]
        )
        return super().get_queryset(request).annotate(_plan_code=Subquery(current_plan))

    # Columns ------------------------------------------------------------------------------

    @admin.display(description=_("adresse"), ordering="slug")
    def public_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">/{}</a>', obj.get_absolute_url(), obj.slug)

    @admin.display(description=_("téléphone du compte"), ordering="user__phone")
    def owner_phone(self, obj):
        return obj.user.phone

    @admin.display(description=_("vérifié"), boolean=True, ordering="verified_at")
    def verified(self, obj):
        return obj.verified_at is not None

    @staticmethod
    def _plan_of(obj) -> str:
        if hasattr(obj, "_plan_code"):
            return obj._plan_code or Plan.Code.FREE
        return billing.current_plan_code(obj)

    @admin.display(description=_("offre"))
    def plan(self, obj):
        return self._plan_of(obj)

    @admin.display(description=_("offre actuelle"))
    def current_plan(self, obj):
        return self._plan_of(obj) if obj.pk else "—"

    @admin.display(description=_("taille de la photo"))
    def photo_size(self, obj):
        return f"{obj.photo_width} × {obj.photo_height} px" if obj.photo_width else "—"

    @admin.display(description=_("adresse"))
    def slug_with_change_link(self, obj):
        if not obj.pk:
            return _("générée automatiquement")
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">/{}</a> · <a href="{}">{}</a>',
            obj.get_absolute_url(),
            obj.slug,
            reverse("admin:profiles_profile_change_slug", args=[obj.pk]),
            _("changer l'adresse"),
        )

    @admin.display(description=_("blocages d'indexation"))
    def indexability(self, obj):
        if not obj.pk:
            return "—"
        blockers = services.indexability_blockers(obj)
        return " · ".join(str(b) for b in blockers) if blockers else _("Aucun : page indexable")

    # Permissions --------------------------------------------------------------------------

    def has_add_permission(self, request):
        return False  # profiles are created by get_or_create_profile (sign-up, card, agent)

    def has_delete_permission(self, request, obj=None):
        return False  # a hard delete would free the slug: erasure goes through services.delete_profile

    def has_grant_subscription_permission(self, request):
        return request.user.has_perm("profiles.grant_subscription")

    def has_erase_permission(self, request):
        return request.user.has_perm("profiles.erase_profile")

    # Saving -------------------------------------------------------------------------------

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        services.refresh_seo_state(form.instance)

    # Slug change view ---------------------------------------------------------------------

    def get_urls(self):
        custom = [
            path(
                "<int:pk>/changer-adresse/",
                self.admin_site.admin_view(self.change_slug_view),
                name="profiles_profile_change_slug",
            )
        ]
        return custom + super().get_urls()

    def change_slug_view(self, request, pk):
        profile = get_object_or_404(Profile, pk=pk)
        if not self.has_change_permission(request, profile):
            return redirect("admin:index")
        form = ChangeSlugForm(request.POST or None, profile=profile, initial={"new_slug": profile.slug})
        if request.method == "POST" and form.is_valid():
            try:
                services.change_slug(profile, form.cleaned_data["new_slug"])
            except ValidationError as exc:
                form.add_error("new_slug", exc.messages)
            else:
                self.message_user(
                    request, _("Nouvelle adresse : /%(slug)s (l'ancienne redirige en 301).") % {"slug": profile.slug}
                )
                return redirect("admin:profiles_profile_change", profile.pk)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": profile,
            "form": form,
            "title": _("Changer l'adresse de %(name)s") % {"name": profile.display_name},
        }
        return TemplateResponse(request, "admin/profiles/profile/change_slug.html", context)

    # Actions ------------------------------------------------------------------------------

    @admin.action(permissions=["change"], description=_("Donner le badge vérifié"))
    def verify(self, request, queryset):
        count = queryset.filter(verified_at__isnull=True).update(verified_at=timezone.now())
        self.message_user(request, _("%(n)d profil(s) vérifié(s).") % {"n": count}, messages.SUCCESS)

    @admin.action(permissions=["change"], description=_("Retirer le badge vérifié"))
    def unverify(self, request, queryset):
        count = queryset.update(verified_at=None)
        self.message_user(request, _("Badge retiré sur %(n)d profil(s).") % {"n": count}, messages.SUCCESS)

    @admin.action(permissions=["change"], description=_("Suspendre"))
    def suspend(self, request, queryset):
        count = 0
        for profile in queryset.filter(status=Profile.Status.ACTIVE):
            services.suspend_profile(profile, str(_("Suspendu par l'administration")))
            count += 1
        self.message_user(request, _("%(n)d profil(s) suspendu(s).") % {"n": count}, messages.SUCCESS)

    @admin.action(permissions=["change"], description=_("Réactiver"))
    def reactivate(self, request, queryset):
        count = 0
        for profile in queryset.filter(status=Profile.Status.SUSPENDED):
            services.reactivate_profile(profile)
            count += 1
        self.message_user(request, _("%(n)d profil(s) réactivé(s).") % {"n": count}, messages.SUCCESS)

    @admin.action(permissions=["change"], description=_("Recalculer le SEO"))
    def recompute_seo(self, request, queryset):
        for profile in queryset:
            services.refresh_seo_state(profile, content_changed=False)
        self.message_user(request, _("SEO recalculé."), messages.SUCCESS)

    def _grant(self, request, queryset, code):
        plan = Plan.objects.filter(code=code).first()
        if plan is None:
            self.message_user(request, _("L'offre « %(code)s » n'existe pas.") % {"code": code}, messages.ERROR)
            return
        count = 0
        for profile in queryset.exclude(status=Profile.Status.DELETED):
            billing.grant_plan(
                profile,
                plan,
                days=365,
                source=Subscription.Source.MANUAL,
                created_by=request.user,
                note=str(_("Attribué depuis l'administration")),
            )
            count += 1
        self.message_user(
            request, _("%(plan)s attribué pour 1 an à %(n)d profil(s).") % {"plan": plan.name, "n": count}
        )

    @admin.action(permissions=["grant_subscription"], description=_("Offrir Essentiel pour 1 an"))
    def grant_essentiel(self, request, queryset):
        self._grant(request, queryset, Plan.Code.ESSENTIEL)

    @admin.action(permissions=["grant_subscription"], description=_("Offrir Pro pour 1 an"))
    def grant_pro(self, request, queryset):
        self._grant(request, queryset, Plan.Code.PRO)

    @admin.action(permissions=["change"], description=_("Notifier les moteurs de recherche"))
    def queue_indexing(self, request, queryset):
        urls = [p.absolute_url for p in queryset.filter(is_indexable=True)]
        queue_urls(urls)
        self.message_user(request, _("%(n)d URL ajoutée(s) à la file d'indexation.") % {"n": len(urls)})

    @admin.action(permissions=["erase"], description=_("Effacer définitivement (droit à l'effacement)"))
    def erase_permanently(self, request, queryset):
        """Right to erasure, with an intermediate confirmation page (irreversible)."""
        profiles = list(queryset.exclude(status=Profile.Status.DELETED).select_related("user"))
        if not profiles:
            self.message_user(request, _("Aucun profil à effacer."), messages.WARNING)
            return None
        if request.POST.get("confirm_erase") == "yes":
            for profile in profiles:
                services.delete_profile(profile)
            self.message_user(
                request,
                _("%(n)d profil(s) effacé(s) définitivement. Leurs adresses répondent maintenant 410.")
                % {"n": len(profiles)},
                messages.SUCCESS,
            )
            return None
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Effacer définitivement ces profils ?"),
            "profiles": profiles,
            "action_name": "erase_permanently",
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/profiles/profile/erase_confirmation.html", context)


@admin.register(SlugRegistry)
class SlugRegistryAdmin(admin.ModelAdmin):
    list_display = ("slug", "kind", "profile_link", "reason", "created_at")
    list_filter = ("kind", "reason")
    search_fields = ("slug", "profile__display_name", "profile__slug")
    list_select_related = ("profile",)

    @admin.display(description=_("profil"))
    def profile_link(self, obj):
        if obj.profile_id is None:
            return "—"
        return format_html(
            '<a href="{}">{}</a>', reverse("admin:profiles_profile_change", args=[obj.profile_id]), obj.profile
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
