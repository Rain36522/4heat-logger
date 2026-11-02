from django import forms

from .core.journal import format_value
from .models import Parameter, SettingChange, now_local

INPUT_FORMATS = [
    "%Y-%m-%dT%H:%M",  # <input type="datetime-local">
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y %H:%M",
]


class SettingChangeForm(forms.Form):
    """Quick entry of a change, made for a phone in front of the heating."""

    parameter = forms.CharField(
        label="Paramètre",
        max_length=32,
        widget=forms.TextInput(attrs={"list": "parameter-codes", "autocomplete": "off", "autocapitalize": "off"}),
    )
    new_value = forms.CharField(label="Nouvelle valeur", max_length=32)
    timestamp = forms.DateTimeField(
        label="Date et heure",
        initial=now_local,
        input_formats=INPUT_FORMATS,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    comment = forms.CharField(label="Commentaire", max_length=300, required=False)

    def clean_parameter(self):
        code = self.cleaned_data["parameter"].strip()
        parameter = Parameter.objects.filter(code__iexact=code).first()
        if parameter is None:
            raise forms.ValidationError(
                f"Paramètre « {code} » inconnu. Ajoute-le d'abord dans l'administration."
            )
        return parameter

    def clean_new_value(self):
        return format_value(self.cleaned_data["new_value"])

    def clean(self):
        cleaned = super().clean()
        parameter, new_value = cleaned.get("parameter"), cleaned.get("new_value")
        if parameter and new_value and new_value == parameter.current_value:
            self.add_error("new_value", f"{parameter.code} vaut déjà {new_value}.")
        return cleaned

    def save(self) -> SettingChange:
        data = self.cleaned_data
        return SettingChange.objects.create(
            parameter=data["parameter"],
            timestamp=data["timestamp"],
            new_value=data["new_value"],
            comment=data["comment"],
        )
