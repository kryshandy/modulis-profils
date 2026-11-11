"""Shared form pieces for the OTP channel choice (dashboard login and card activation)."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _


def channel_field() -> forms.ChoiceField:
    # Optional: an old form or a client without the radios falls back to the default channel.
    return forms.ChoiceField(label=_("Comment veux-tu recevoir ton code ?"), required=False, choices=())


class ChannelChoiceMixin:
    """Adds the `channel` choice, limited to the channels available right now (default first)."""

    def setup_channels(self, channels) -> None:
        self.channels = list(channels)
        field = self.fields["channel"]
        field.choices = [(c.code, c.choice_label) for c in self.channels]
        field.initial = self.channels[0].code if self.channels else ""

    def selected_channel_code(self) -> str:
        if self.is_bound:
            value = self.data.get(self.add_prefix("channel"), "")
            if any(c.code == value for c in self.channels):
                return value
        return self.fields["channel"].initial or ""

    def channel_options(self) -> list[dict]:
        selected = self.selected_channel_code()
        return [
            {
                "code": c.code,
                "label": c.choice_label,
                "help": c.choice_help,
                "recommended": c.recommended and len(self.channels) > 1,
                "checked": c.code == selected,
                "id": f"id_channel_{index}",
            }
            for index, c in enumerate(self.channels)
        ]
