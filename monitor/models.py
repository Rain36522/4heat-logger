import re

from django.db import models
from django.utils import timezone

from .core.journal import ChangeRecord, current_value, format_value, value_before


def now_local():
    """Current local time to the minute (the app stores naive local datetimes, like the CSV)."""
    return timezone.now().replace(second=0, microsecond=0)


class Parameter(models.Model):
    """One setting of the heating (UA01, T06, C01...), with its legend."""

    code = models.CharField("code", max_length=32, unique=True)
    # Letters of the code ("UA", "T", "O"...), kept to filter the long list in the admin.
    family = models.CharField(max_length=8, editable=False, db_index=True, default="")
    # Title row above the parameter in the Excel sheet ("Ventilateur 1", "Temps"...).
    section = models.CharField("section", max_length=100, blank=True)
    description = models.CharField("description", max_length=200, blank=True)
    unit = models.CharField("unité", max_length=16, blank=True)
    state_label = models.CharField("état concerné", max_length=64, blank=True)
    baseline_value = models.CharField("valeur de base", max_length=32, blank=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "paramètre"
        verbose_name_plural = "paramètres"

    def __str__(self):
        detail = self.description or self.section
        return f"{self.code} — {detail}" if detail else self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip()
        self.family = re.match(r"[A-Za-z]*", self.code).group(0).upper()
        super().save(*args, **kwargs)

    def _records(self, exclude_pk=None):
        queryset = self.changes.all()
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        return [ChangeRecord(change.pk, change.timestamp, change.new_value) for change in queryset]

    @property
    def current_value(self) -> str:
        return current_value(self.baseline_value, self._records())

    def value_before(self, when, exclude_pk=None) -> str:
        return value_before(self.baseline_value, self._records(exclude_pk), when, exclude_pk)


class SettingChange(models.Model):
    """One change of one parameter, made by hand on the heating."""

    timestamp = models.DateTimeField("date et heure", default=now_local, db_index=True)
    time_is_approximate = models.BooleanField("heure approximative", default=False)
    parameter = models.ForeignKey(
        Parameter, on_delete=models.CASCADE, related_name="changes", verbose_name="paramètre"
    )
    old_value = models.CharField("ancienne valeur", max_length=32, blank=True)
    new_value = models.CharField("nouvelle valeur", max_length=32)
    comment = models.CharField("commentaire", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        verbose_name = "changement de réglage"
        verbose_name_plural = "changements de réglages"

    def __str__(self):
        return f"{self.parameter.code}: {self.old_value or '∅'} → {self.new_value}"

    def save(self, *args, **kwargs):
        self.new_value = format_value(self.new_value)
        # The previous value is never typed by hand: it is whatever the parameter had before.
        if not self.old_value:
            self.old_value = self.parameter.value_before(self.timestamp, exclude_pk=self.pk)
        self.old_value = format_value(self.old_value)
        super().save(*args, **kwargs)


class CodeLabel(models.Model):
    """Readable name for a state number or an error code, shown instead of the bare number."""

    class Kind(models.TextChoices):
        STATE = "state", "État"
        ERROR = "error", "Défaut"

    kind = models.CharField("type", max_length=8, choices=Kind.choices)
    code = models.PositiveSmallIntegerField("code")
    name = models.CharField("libellé", max_length=100)

    class Meta:
        ordering = ["kind", "code"]
        verbose_name = "libellé de code"
        verbose_name_plural = "libellés de codes"
        constraints = [models.UniqueConstraint(fields=("kind", "code"), name="unique_kind_code")]

    def __str__(self):
        return f"{self.get_kind_display()} {self.code} : {self.name}"

    @classmethod
    def labels(cls, kind) -> dict[int, str]:
        return dict(cls.objects.filter(kind=kind).values_list("code", "name"))


class AlertState(models.Model):
    """What the alerter remembers between two runs (a single row)."""

    active_code = models.IntegerField(default=0)
    active_since = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    pending_code = models.IntegerField(null=True, blank=True)
    pending_count = models.PositiveSmallIntegerField(default=0)
    pending_since = models.DateTimeField(null=True, blank=True)
    last_processed = models.DateTimeField(null=True, blank=True)

    @classmethod
    def load(cls) -> "AlertState":
        row, _ = cls.objects.get_or_create(pk=1)
        return row
