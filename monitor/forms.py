from django import forms

from .core.journal import format_value
from .models import DAY_CHOICES, DayOff, Parameter, ScheduleSlot, SettingChange, now_local

EVERY_DAY = ""
SLOT_DAY_CHOICES = [(EVERY_DAY, "Tous les jours"), *DAY_CHOICES]

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


class BoilerTargetForm(forms.Form):
    # Rough bounds only: the real limits are read from the module before writing.
    value = forms.IntegerField(label="Consigne chaudière (°C)", min_value=20, max_value=90)


class ScheduleSlotForm(forms.ModelForm):
    """Start day "Tous les jours" = a daily slot (the end day is then ignored)."""

    start_day = forms.TypedChoiceField(
        label="Début", choices=SLOT_DAY_CHOICES, coerce=int, empty_value=None, required=False
    )
    end_day = forms.TypedChoiceField(
        label="Fin", choices=SLOT_DAY_CHOICES, coerce=int, empty_value=None, required=False
    )

    class Meta:
        model = ScheduleSlot
        fields = ["start_day", "start_time", "end_day", "end_time"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start_day") is None:
            cleaned["end_day"] = None
        elif cleaned.get("end_day") is None:
            self.add_error("end_day", "Choisis le jour de fin (ou « Tous les jours » au début).")
        return cleaned


class DayOffForm(forms.ModelForm):
    """A single day when "au" is left empty."""

    class Meta:
        model = DayOff
        fields = ["first_day", "last_day", "label"]
        widgets = {
            "first_day": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "last_day": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "label": forms.TextInput(attrs={"placeholder": "ex. Noël, vacances"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["last_day"].required = False

    def clean(self):
        cleaned = super().clean()
        first, last = cleaned.get("first_day"), cleaned.get("last_day")
        if first and not last:
            cleaned["last_day"] = first
        elif first and last and last < first:
            self.add_error("last_day", "La fin est avant le début.")
        return cleaned
