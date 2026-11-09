from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Report


class ReportForm(forms.Form):
    reason = forms.ChoiceField(label=_("Motif du signalement"), choices=Report.Reason.choices, widget=forms.RadioSelect)
    message = forms.CharField(
        label=_("Explique-nous ce qui ne va pas"),
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    contact = forms.CharField(
        label=_("Ton téléphone ou ton email (facultatif)"),
        max_length=120,
        required=False,
        help_text=_("Seulement si tu acceptes que notre équipe te recontacte."),
    )
    # Honeypot: hidden by CSS, real people leave it empty.
    website = forms.CharField(
        required=False,
        label=_("Ne pas remplir"),
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}),
    )

    def is_spam(self) -> bool:
        return bool(self.cleaned_data.get("website"))
