"""Read the settings workbook (Heater_data sheet) into an import plan.

Expected layout, as in Liste_Parametres2.xlsx:
  - column A: parameter code; column B: baseline value (first known state);
  - row 2: the date of each column (a column = one session of changes);
  - columns C and following: only the values that changed in that session.
Columns without a date cannot be placed in time: they are reported as `pending`
and must be entered by hand (with an approximate date) in the app.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

from .journal import format_value

DATE_FORMATS = ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y")
EXCEL_EPOCH = datetime(1899, 12, 30)


@dataclass(frozen=True)
class PlannedChange:
    when: datetime | None  # None = the column has no date
    column: str  # spreadsheet column letter, to help the user find it
    code: str
    old_value: str
    new_value: str


@dataclass
class ImportPlan:
    baseline_date: datetime | None = None
    baselines: dict[str, str] = field(default_factory=dict)  # code -> baseline value
    sections: dict[str, str] = field(default_factory=dict)  # code -> title row above it
    changes: list[PlannedChange] = field(default_factory=list)  # dated, oldest first
    pending: list[PlannedChange] = field(default_factory=list)  # undated columns
    snapshot: dict[str, str] = field(default_factory=dict)  # "current values" sheet
    skipped_rows: list[str] = field(default_factory=list)  # title rows without values

    def final_values(self, include_pending: bool = True) -> dict[str, str]:
        """Value of every parameter after applying the planned changes in order."""
        values = dict(self.baselines)
        for change in self.changes + (self.pending if include_pending else []):
            values[change.code] = change.new_value
        return values

    def snapshot_differences(self, include_pending: bool) -> list[tuple[str, str, str]]:
        """(code, value after import, value in the snapshot sheet) where they differ."""
        final = self.final_values(include_pending)
        return [
            (code, final[code], expected)
            for code, expected in sorted(self.snapshot.items())
            if code in final and final[code] != expected
        ]


def parse_session_date(value) -> datetime | None:
    """Turn a date cell (datetime, text such as '15.01.26', Excel serial) into a datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)) and 30000 < value < 80000:
        return EXCEL_EPOCH + timedelta(days=float(value))
    text = str(value).strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def parse_workbook(
    path,
    sheet: str = "Heater_data",
    snapshot_sheet: str | None = "Feuil1",
    date_row: int = 2,
) -> ImportPlan:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl complains about the print area name
        workbook = openpyxl.load_workbook(Path(path), data_only=True)

    rows = list(workbook[sheet].iter_rows(values_only=True))
    date_cells = rows[date_row - 1]
    width = max(len(row) for row in rows)

    plan = ImportPlan(baseline_date=parse_session_date(date_cells[1] if len(date_cells) > 1 else None))
    sessions = []  # (column index, letter, date or None) for column C and following
    for index in range(2, width):
        when = parse_session_date(date_cells[index] if index < len(date_cells) else None)
        sessions.append((index, get_column_letter(index + 1), when))

    section = ""
    for row in rows[date_row:]:
        code = str(row[0]).strip() if row and row[0] is not None else ""
        if not code:
            continue
        cells = [format_value(row[index]) if index < len(row) else "" for index in range(width)]
        if not any(cells[1:]):
            # A row without any value is a section title ("Ventilateur 1", "Temps"...):
            # it labels the parameters listed below it, up to the next title.
            plan.skipped_rows.append(code)
            section = code
            continue

        baseline = cells[1]
        plan.baselines[code] = baseline
        plan.sections[code] = section
        previous = baseline
        for index, letter, when in sessions:
            value = cells[index]
            if not value or value == previous:
                continue
            change = PlannedChange(when, letter, code, previous, value)
            (plan.changes if when else plan.pending).append(change)
            previous = value

    plan.changes.sort(key=lambda change: (change.when, change.code))

    if snapshot_sheet and snapshot_sheet in workbook.sheetnames:
        for row in workbook[snapshot_sheet].iter_rows(values_only=True):
            if row and row[0] is not None and len(row) > 1 and row[1] is not None:
                plan.snapshot[str(row[0]).strip()] = format_value(row[1])
    return plan
