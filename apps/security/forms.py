from django import forms
from django.utils.translation import gettext_lazy as _


class EnrollForm(forms.Form):
    code = forms.CharField(
        label=_("Code à 6 chiffres affiché par l'application"),
        max_length=12,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "autofocus": True,
                "class": "mx-2fa-code",
                "spellcheck": "false",
            }
        ),
    )


class VerifyForm(forms.Form):
    code = forms.CharField(
        label=_("Code de l'application (6 chiffres) ou code de secours"),
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "autofocus": True,
                "class": "mx-2fa-code",
                "spellcheck": "false",
                "autocapitalize": "off",
            }
        ),
    )
