from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import ChannelChoiceMixin, channel_field
from apps.core.models import City, Trade

from .models import CardBatch


class ActivationCodeForm(forms.Form):
    activation_code = forms.CharField(
        label=_("Code d'activation"),
        max_length=20,
        help_text=_("8 caractères, imprimés sous la zone à gratter ou sur l'encart de la carte."),
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "autocapitalize": "characters", "spellcheck": "false", "autofocus": True}
        ),
    )


class PhoneForm(ChannelChoiceMixin, forms.Form):
    phone = forms.CharField(
        label=_("Ton numéro de téléphone"),
        max_length=30,
        help_text=_("Tu vas recevoir un code par WhatsApp ou par SMS."),
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "inputmode": "tel", "autofocus": True}),
    )
    channel = channel_field()

    def __init__(self, *args, channels=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_channels(channels)


class OTPForm(forms.Form):
    code = forms.CharField(
        label=_("Code reçu"),
        max_length=10,
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "pattern": "[0-9 ]*", "autofocus": True}
        ),
    )


class NewProfileForm(forms.Form):
    display_name = forms.CharField(
        label=_("Ton nom ou le nom de ton activité"),
        max_length=80,
        widget=forms.TextInput(attrs={"autocomplete": "name", "autofocus": True}),
    )
    trade = forms.ModelChoiceField(
        label=_("Ton métier"), queryset=Trade.objects.none(), required=False, empty_label=_("— Choisir —")
    )
    city = forms.ModelChoiceField(
        label=_("Ta ville"), queryset=City.objects.none(), required=False, empty_label=_("— Choisir —")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["trade"].queryset = Trade.objects.filter(is_active=True).order_by("name")
        self.fields["city"].queryset = City.objects.filter(is_active=True, country__is_active=True).order_by("name")


NEW_PROFILE = "new"


class ChooseProfileForm(forms.Form):
    """Existing account: link the card to one of its pages (or create a new one if the plan allows)."""

    profile = forms.ChoiceField(label=_("Associer cette carte à"), widget=forms.RadioSelect)

    def __init__(self, *args, profiles=(), allow_new: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.profiles = {str(p.pk): p for p in profiles}
        choices = [(pk, f"{p.display_name} — /{p.slug}") for pk, p in self.profiles.items()]
        if allow_new:
            choices.append((NEW_PROFILE, _("Créer une nouvelle page")))
        self.fields["profile"].choices = choices
        if len(choices) == 1:
            self.fields["profile"].initial = choices[0][0]

    def selected_profile(self):
        return self.profiles.get(self.cleaned_data["profile"])


class GenerateBatchForm(forms.Form):
    reference = forms.CharField(label=_("Référence du lot"), max_length=40)
    quantity = forms.IntegerField(label=_("Quantité"), min_value=1, max_value=20000)
    kind = forms.ChoiceField(label=_("Type"), choices=CardBatch.Kind.choices, initial=CardBatch.Kind.STANDARD)
    supplier = forms.CharField(label=_("Fournisseur"), max_length=120, required=False)

    def clean_reference(self):
        reference = self.cleaned_data["reference"].strip()
        if CardBatch.objects.filter(reference__iexact=reference).exists():
            raise forms.ValidationError(_("Cette référence de lot existe déjà."))
        return reference
