"""Rules of the settings journal (no Django, so they can be tested on their own).

A parameter has a baseline value (the first known one) and a list of changes.
Its "current value" is the new value of the latest change, or the baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable


def format_value(raw) -> str:
    """Normalise a value coming from a spreadsheet or a form.

    '120.0' -> '120', 3.30 -> '3.3', '3,5' -> '3.5'. Text stays text.
    """
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "1" if raw else "0"
    text = str(raw).strip()
    try:
        number = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return text
    if not number.is_finite():
        return text
    return format(number.normalize(), "f")


@dataclass(frozen=True)
class ChangeRecord:
    pk: int | None
    timestamp: datetime
    new_value: str


def current_value(baseline: str, changes: Iterable[ChangeRecord]) -> str:
    """New value of the latest change, or the baseline when there is none."""
    latest = max(changes, key=lambda change: (change.timestamp, change.pk or 0), default=None)
    return latest.new_value if latest else baseline


def value_before(
    baseline: str,
    changes: Iterable[ChangeRecord],
    when: datetime,
    exclude_pk: int | None = None,
) -> str:
    """Value the parameter had just before `when`."""
    earlier = [
        change
        for change in changes
        if change.timestamp < when and (exclude_pk is None or change.pk != exclude_pk)
    ]
    return current_value(baseline, earlier)
