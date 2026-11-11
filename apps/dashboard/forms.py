"""Forms of the Espace pro. Labels are short and concrete; errors are in plain French."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import ChannelChoiceMixin, channel_field
from apps.accounts.services import InvalidPhone, normalize_phone
from apps.core.models import City, Trade
from apps.profiles.models import Profile, ProfileLink, ProfileService
from apps.profiles.services import OPENING_DAYS, TIME_RE

from .services import COVER_COLORS

OTHER_TRADE = "other"


def profile_values(form: forms.ModelForm) -> dict:
    """Values of a validated profile ModelForm, ready for `profiles.services.update_profile`.

    The form is only used for validation (`save(commit=False)`): the service writes.
    """
    instance = form.save(commit=False)
    names = [name for name in form._meta.fields if name in form.fields]
    names += getattr(form, "extra_model_fields", [])
    return {name: getattr(instance, name) for name in names}


def _clean_phone(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        return normalize_phone(value)
    except InvalidPhone as exc:
        raise forms.ValidationError(str(exc)) from exc


# --- Auth ------------------------------------------------------------------------------------


class PhoneForm(ChannelChoiceMixin, forms.Form):
    phone = forms.CharField(
        label=_("Ton numéro de téléphone"),
        max_length=24,
        widget=forms.TextInput(
            attrs={
                "type": "tel",
                "inputmode": "numeric",
                "autocomplete": "tel",
                "placeholder": "6XX XX XX XX",
                "autofocus": True,
            }
        ),
    )
    channel = channel_field()

    def __init__(self, *args, channels=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_channels(channels)


class CodeForm(forms.Form):
    code = forms.CharField(
        label=_("Code reçu par SMS"),
        max_length=12,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9 ]*",
                "maxlength": settings.OTP_LENGTH,
                "placeholder": "••••••",
                "autofocus": True,
                "class": "input--code",
            }
        ),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].replace(" ", "")
        if not code.isdigit() or len(code) != settings.OTP_LENGTH:
            raise forms.ValidationError(_("Le code contient %(n)d chiffres.") % {"n": settings.OTP_LENGTH})
        return code


# --- Profile content -------------------------------------------------------------------------


class IdentityForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["display_name", "kind"]
        labels = {"display_name": _("Ton nom ou le nom de ton activité"), "kind": _("Tu es…")}
        widgets = {
            "display_name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": _("ex. Paul Nkoulou")}),
            "kind": forms.RadioSelect,
        }

    def clean_display_name(self):
        name = " ".join(self.cleaned_data["display_name"].split())
        if len(name) < 2:
            raise forms.ValidationError(_("Écris au moins 2 lettres."))
        return name


class TradeCityForm(forms.ModelForm):
    """Métier (list or free title) + ville + quartier."""

    trade_choice = forms.ChoiceField(label=_("Ton métier"), required=False)
    extra_model_fields = ["trade"]

    class Meta:
        model = Profile
        fields = ["custom_title", "is_feminine", "city", "district", "service_area", "price_range"]
        labels = {
            "custom_title": _("Ton métier, en quelques mots"),
            "is_feminine": _("Afficher mon métier au féminin (ex. « Plombière »)"),
            "city": _("Ta ville"),
            "district": _("Ton quartier"),
            "service_area": _("Où travailles-tu ? (facultatif)"),
            "price_range": _("Tes prix, en gros (facultatif)"),
        }
        help_texts = {"price_range": _("ex. « 5 000–50 000 FCFA ». Google peut l'afficher dans ses résultats.")}
        widgets = {
            "custom_title": forms.TextInput(attrs={"placeholder": _("ex. Réparatrice de téléphones")}),
            "district": forms.TextInput(attrs={"placeholder": _("ex. Akwa, Bonamoussadi…")}),
            "service_area": forms.TextInput(attrs={"placeholder": _("ex. Tout Douala et environs")}),
            "price_range": forms.TextInput(attrs={"placeholder": _("ex. 5 000–50 000 FCFA"), "maxlength": 20}),
        }

    def __init__(self, *args, show_area: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        trades = Trade.objects.filter(is_active=True).order_by("name")
        groups: dict[str, list] = {}
        for trade in trades:
            groups.setdefault(trade.get_segment_display(), []).append((str(trade.pk), trade.name))
        self.fields["trade_choice"].choices = [
            ("", _("— Choisis ton métier —")),
            *groups.items(),
            (OTHER_TRADE, _("Autre : je l'écris moi-même")),
        ]
        if self.instance.trade_id and not self.instance.custom_title:
            self.initial["trade_choice"] = str(self.instance.trade_id)
        elif self.instance.custom_title:
            self.initial["trade_choice"] = OTHER_TRADE
        self.fields["city"].queryset = City.objects.filter(is_active=True, country__is_active=True).order_by("name")
        self.fields["city"].empty_label = _("— Choisis ta ville —")
        self.fields["city"].required = True
        self.fields["custom_title"].required = False
        if not show_area:
            del self.fields["service_area"]
            del self.fields["price_range"]

    def clean(self):
        data = super().clean()
        choice = data.get("trade_choice") or ""
        custom = " ".join((data.get("custom_title") or "").split())
        self._trade = None
        if choice and choice != OTHER_TRADE:
            self._trade = Trade.objects.filter(pk=choice if choice.isdigit() else 0, is_active=True).first()
            if self._trade is None:
                self.add_error("trade_choice", _("Choisis un métier dans la liste."))
            data["custom_title"] = ""
        elif custom:
            data["custom_title"] = custom
        else:
            self.add_error("trade_choice", _("Choisis ton métier, ou écris-le dans « Autre »."))
        return data

    def save(self, commit=False):
        """Validation only: never writes (profiles.services.update_profile does)."""
        profile = super().save(commit=False)
        profile.trade = self._trade
        return profile


class ContactForm(forms.ModelForm):
    # Declared explicitly: people type "+237 6 99 11 22 33" (longer than the stored E.164 form).
    whatsapp = forms.CharField(
        label=_("Ton numéro WhatsApp"),
        max_length=24,
        required=False,
        help_text=_("Tes clients t'écriront directement sur WhatsApp."),
        widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel"}),
    )
    phone_public = forms.CharField(
        label=_("Numéro à appeler"),
        max_length=24,
        required=False,
        widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel"}),
    )
    maps_url = forms.URLField(
        label=_("Lien Google Maps (facultatif)"),
        required=False,
        max_length=200,
        assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://maps.app.goo.gl/…", "inputmode": "url"}),
    )
    # GPS position (schema.org geo): filled by the "Ma position" button or typed by hand.
    latitude = forms.DecimalField(
        label=_("Latitude"),
        required=False,
        min_value=-90,
        max_value=90,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "4.051056", "data-geo": "lat"}),
    )
    longitude = forms.DecimalField(
        label=_("Longitude"),
        required=False,
        min_value=-180,
        max_value=180,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "9.767869", "data-geo": "lng"}),
    )

    class Meta:
        model = Profile
        fields = ["whatsapp", "phone_public", "email_public", "address", "maps_url", "latitude", "longitude"]
        labels = {
            "whatsapp": _("Ton numéro WhatsApp"),
            "phone_public": _("Numéro à appeler"),
            "email_public": _("Ton email (facultatif)"),
            "address": _("Adresse ou repère (facultatif)"),
            "maps_url": _("Lien Google Maps (facultatif)"),
        }
        help_texts = {
            "whatsapp": _("Tes clients t'écriront directement sur WhatsApp."),
            "address": _("ex. Face à la pharmacie du marché, Akwa"),
        }
        widgets = {
            "whatsapp": forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel"}),
            "phone_public": forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel"}),
            "email_public": forms.EmailInput(attrs={"autocomplete": "email", "inputmode": "email"}),
            "maps_url": forms.URLInput(attrs={"placeholder": "https://maps.app.goo.gl/…", "inputmode": "url"}),
        }

    def __init__(self, *args, short: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if short:
            for name in ("address", "maps_url", "latitude", "longitude"):
                del self.fields[name]
        if self.instance and self.instance.pk:
            from apps.accounts.services import display_phone

            for name in ("whatsapp", "phone_public"):
                if getattr(self.instance, name):
                    self.initial[name] = display_phone(getattr(self.instance, name))

    def clean_whatsapp(self):
        return _clean_phone(self.cleaned_data.get("whatsapp"))

    def clean_phone_public(self):
        return _clean_phone(self.cleaned_data.get("phone_public"))

    def clean_maps_url(self):
        url = (self.cleaned_data.get("maps_url") or "").strip()
        if url and urlsplit(url).scheme != "https":
            raise forms.ValidationError(_("Le lien doit commencer par https://"))
        return url

    def _clean_coordinate(self, name):
        value = self.cleaned_data.get(name)
        return None if value is None else value.quantize(Decimal("0.000001"))

    def clean_latitude(self):
        return self._clean_coordinate("latitude")

    def clean_longitude(self):
        return self._clean_coordinate("longitude")

    def clean(self):
        data = super().clean()
        if ("latitude" in self.fields) and (data.get("latitude") is None) != (data.get("longitude") is None):
            self.add_error("longitude", _("Indique la latitude ET la longitude, ou laisse les deux vides."))
        if not self.errors and not data.get("whatsapp") and not data.get("phone_public"):
            raise forms.ValidationError(
                _("Mets au moins un numéro (WhatsApp ou appel) pour que tes clients te joignent.")
            )
        return data


class BioForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["bio"]
        labels = {"bio": _("Présente-toi en quelques phrases")}
        widgets = {
            "bio": forms.Textarea(
                attrs={
                    "rows": 7,
                    "maxlength": 1500,
                    "data-counter": "1",
                    "data-min": settings.SEO_MIN_BIO_CHARS,
                    "placeholder": _("ex. Je répare les fuites et installe les sanitaires à Douala depuis 10 ans…"),
                }
            )
        }

    def clean_bio(self):
        return (self.cleaned_data.get("bio") or "").strip()


class QuickServicesForm(forms.Form):
    """Onboarding step 5: two services in one go (both optional)."""

    service_1 = forms.CharField(label=_("Prestation 1"), max_length=100, required=False)
    price_1 = forms.CharField(label=_("Prix indicatif"), max_length=60, required=False)
    service_2 = forms.CharField(label=_("Prestation 2"), max_length=100, required=False)
    price_2 = forms.CharField(label=_("Prix indicatif"), max_length=60, required=False)

    def items(self) -> list[tuple[str, str]]:
        data = self.cleaned_data
        return [
            (data[f"service_{i}"].strip(), data[f"price_{i}"].strip())
            for i in (1, 2)
            if data.get(f"service_{i}", "").strip()
        ]


class ServiceForm(forms.ModelForm):
    class Meta:
        model = ProfileService
        fields = ["title", "description", "price_label"]
        labels = {
            "title": _("Nom de la prestation"),
            "description": _("Détail (facultatif)"),
            "price_label": _("Prix indicatif (facultatif)"),
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": _("ex. Réparation de fuite")}),
            "description": forms.TextInput(attrs={"placeholder": _("ex. Intervention en 24 h")}),
            "price_label": forms.TextInput(attrs={"placeholder": _("ex. dès 5 000 FCFA")}),
        }


DAY_LABELS = {
    "mo": _("Lundi"),
    "tu": _("Mardi"),
    "we": _("Mercredi"),
    "th": _("Jeudi"),
    "fr": _("Vendredi"),
    "sa": _("Samedi"),
    "su": _("Dimanche"),
}
_WEEKDAYS = OPENING_DAYS[:5]
_MON_SAT = OPENING_DAYS[:6]
HOURS_PRESETS = {
    "mon_sat_8_18": (_("Lun–Sam 8h–18h"), {day: [["08:00", "18:00"]] for day in _MON_SAT}),
    "mon_fri_8_17": (_("Lun–Ven 8h–17h"), {day: [["08:00", "17:00"]] for day in _WEEKDAYS}),
    "every_day_7_20": (_("Tous les jours 7h–20h"), {day: [["07:00", "20:00"]] for day in OPENING_DAYS}),
}


class OpeningHoursForm(forms.Form):
    """One opening range per day (open/closed + from/to). Stored as profile.opening_hours."""

    def __init__(self, *args, hours: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        hours = hours or {}
        self.days = []
        for day in OPENING_DAYS:
            ranges = hours.get(day) or []
            first = ranges[0] if ranges else ["08:00", "18:00"]
            self.fields[f"{day}_open"] = forms.BooleanField(label=DAY_LABELS[day], required=False, initial=bool(ranges))
            self.fields[f"{day}_from"] = forms.CharField(
                label=_("de"), required=False, initial=first[0], widget=forms.TimeInput(attrs={"type": "time"})
            )
            self.fields[f"{day}_to"] = forms.CharField(
                label=_("à"), required=False, initial=first[1], widget=forms.TimeInput(attrs={"type": "time"})
            )
            self.days.append((day, self[f"{day}_open"], self[f"{day}_from"], self[f"{day}_to"]))

    def clean(self):
        data = super().clean()
        self._hours = {}
        for day in OPENING_DAYS:
            if not data.get(f"{day}_open"):
                continue
            start = (data.get(f"{day}_from") or "").strip()[:5]
            end = (data.get(f"{day}_to") or "").strip()[:5]
            if not (TIME_RE.match(start) and TIME_RE.match(end)) or start >= end:
                self.add_error(
                    f"{day}_to", _("Indique l'heure d'ouverture puis celle de fermeture (ex. 08:00 → 18:00).")
                )
                continue
            self._hours[day] = [[start, end]]
        return data

    def hours(self) -> dict:
        return self._hours


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MediaUploadForm(forms.Form):
    """Rendering only: the view reads `request.FILES.getlist("images")` and validates each file."""

    images = forms.FileField(
        label=_("Ajouter des photos de ton travail"),
        widget=MultipleImageInput(attrs={"accept": "image/*", "multiple": True}),
    )
    caption = forms.CharField(label=_("Légende (facultatif)"), max_length=140, required=False)


class CaptionForm(forms.Form):
    caption = forms.CharField(label=_("Légende"), max_length=140, required=False)


class LinkForm(forms.ModelForm):
    url = forms.URLField(
        label=_("Adresse du lien"),
        max_length=300,
        assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://", "inputmode": "url"}),
    )

    class Meta:
        model = ProfileLink
        fields = ["kind", "url"]
        labels = {"kind": _("Type de lien")}

    def clean_url(self):
        url = (self.cleaned_data.get("url") or "").strip()
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.netloc:
            raise forms.ValidationError(_("Le lien doit commencer par https://"))
        return url


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["cover_color", "visibility"]
        labels = {"cover_color": _("Couleur de ta page"), "visibility": _("Qui peut voir ta page ?")}
        widgets = {"visibility": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cover_color"] = forms.ChoiceField(
            label=_("Couleur de ta page"), choices=COVER_COLORS, widget=forms.RadioSelect
        )


# --- Settings --------------------------------------------------------------------------------


class SlugForm(forms.Form):
    slug = forms.CharField(
        label=_("Nouvelle adresse"),
        max_length=50,
        widget=forms.TextInput(attrs={"autocapitalize": "none", "autocorrect": "off", "spellcheck": "false"}),
    )

    def clean_slug(self):
        return self.cleaned_data["slug"].strip().lower()


class LanguageForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["language"]
        labels = {"language": _("Langue de ta page")}
        widgets = {"language": forms.RadioSelect}


class RecoveryEmailForm(forms.Form):
    email = forms.EmailField(
        label=_("Ton email"),
        required=False,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "inputmode": "email"}),
    )


class DeleteProfileForm(forms.Form):
    confirm = forms.CharField(label=_("Écris l'adresse de ta page pour confirmer"), max_length=60)

    def __init__(self, *args, expected: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected = expected
        self.fields["confirm"].widget.attrs.update({"autocapitalize": "none", "autocomplete": "off"})

    def clean_confirm(self):
        value = self.cleaned_data["confirm"].strip().lower()
        if value != self.expected:
            raise forms.ValidationError(_("Ce n'est pas la bonne adresse. Recopie-la exactement."))
        return value


class LinkCardForm(forms.Form):
    public_code = forms.CharField(
        label=_("Code de la carte"),
        max_length=12,
        help_text=_("Les 7 caractères écrits au dos, sous le QR code."),
        widget=forms.TextInput(attrs={"autocapitalize": "characters", "autocomplete": "off", "spellcheck": "false"}),
    )
    activation_code = forms.CharField(
        label=_("Code d'activation"),
        max_length=16,
        help_text=_("Les 8 caractères sous la zone à gratter."),
        widget=forms.TextInput(attrs={"autocapitalize": "characters", "autocomplete": "off", "spellcheck": "false"}),
    )
