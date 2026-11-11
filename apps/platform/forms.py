"""Control center sections: one small ModelForm per section, posted separately (works without JS)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import SiteSettings


@dataclass(frozen=True)
class Section:
    code: str
    title: str
    description: str
    fields: tuple[str, ...]
    # field -> (value considered dangerous, explanation shown on the confirmation step)
    dangerous: dict = field(default_factory=dict)


SECTIONS: tuple[Section, ...] = (
    Section(
        "auth",
        _("Authentification"),
        _("Canaux d'envoi du code de connexion, ouverture de la connexion et des inscriptions."),
        (
            "otp_whatsapp_enabled",
            "otp_firebase_sms_enabled",
            "otp_sms_gateway_enabled",
            "otp_default_channel",
            "login_enabled",
            "signups_enabled",
        ),
        {
            "login_enabled": (False, _("Plus aucun pro ne pourra se connecter à son espace.")),
            "signups_enabled": (False, _("Plus personne ne pourra créer de compte.")),
        },
    ),
    Section(
        "cards",
        _("Cartes NFC"),
        _("Activation des cartes par code secret."),
        ("card_activation_enabled",),
    ),
    Section(
        "pages",
        _("Pages et modèles"),
        _("Création de nouvelles pages pros et choix du modèle de site."),
        ("page_creation_enabled", "themes_enabled"),
    ),
    Section(
        "directory",
        _("Annuaire"),
        _("Pages villes et métiers (référencement local)."),
        ("directory_enabled",),
    ),
    Section(
        "reports",
        _("Signalements"),
        _("Formulaire public « Signaler cette page »."),
        ("reports_enabled",),
    ),
    Section(
        "seo",
        _("SEO et indexation"),
        _("Notifications envoyées aux moteurs de recherche avec kliz."),
        ("indexing_notifications_enabled", "instant_publish_enabled"),
    ),
    Section(
        "maintenance",
        _("Maintenance"),
        _("Coupe le site public (réponse 503). L'équipe et l'administration restent accessibles."),
        ("maintenance_mode", "maintenance_message"),
        {"maintenance_mode": (True, _("Tout le site public affichera la page de maintenance."))},
    ),
    Section(
        "announcement",
        _("Annonce"),
        _("Bandeau affiché aux pros dans leur espace. Laisse vide pour le retirer."),
        ("announcement",),
    ),
)
SECTIONS_BY_CODE = {s.code: s for s in SECTIONS}

OTP_FLAGS = {
    SiteSettings.OtpChannel.WHATSAPP: "otp_whatsapp_enabled",
    SiteSettings.OtpChannel.FIREBASE_SMS: "otp_firebase_sms_enabled",
    SiteSettings.OtpChannel.SMS_GATEWAY: "otp_sms_gateway_enabled",
}


class BaseSectionForm(forms.ModelForm):
    section: Section

    def clean(self):
        cleaned = super().clean()
        if self.section.code == "auth":
            enabled = [code for code, flag in OTP_FLAGS.items() if cleaned.get(flag)]
            default = cleaned.get("otp_default_channel")
            if enabled and default not in enabled:
                self.add_error("otp_default_channel", _("Le canal par défaut doit faire partie des canaux activés."))
        return cleaned

    def dangerous_changes(self, current: SiteSettings) -> list[str]:
        """Explanations of the dangerous switches this submission would flip."""
        out = []
        for name, (value, explanation) in self.section.dangerous.items():
            if self.cleaned_data.get(name) == value and getattr(current, name) != value:
                out.append(f"{self.fields[name].label} : {explanation}")
        return out


def form_class(section: Section) -> type[BaseSectionForm]:
    widgets = {}
    if "maintenance_message" in section.fields:
        widgets["maintenance_message"] = forms.Textarea(attrs={"rows": 2})
    if "announcement" in section.fields:
        widgets["announcement"] = forms.Textarea(attrs={"rows": 2})
    form = forms.modelform_factory(SiteSettings, form=BaseSectionForm, fields=section.fields, widgets=widgets)
    form.section = section
    return form


def build_forms(instance: SiteSettings, bound_section: str | None = None, data=None) -> dict[str, BaseSectionForm]:
    forms_ = {}
    for section in SECTIONS:
        cls = form_class(section)
        if section.code == bound_section:
            forms_[section.code] = cls(data, instance=copy.copy(instance), prefix=section.code)
        else:
            forms_[section.code] = cls(instance=instance, prefix=section.code)
    return forms_
