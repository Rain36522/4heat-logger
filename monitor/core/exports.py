"""Build CSV files for download (no Django, so it can be tested on its own).

The format is the one Excel expects with French/Swiss settings, as in the workbook
exported by hand (Liste_Parametres2.csv): ";" between columns, "," as decimal mark,
UTF-8 with a BOM so accents are read correctly.
Numbers stored as text ("2.6", "120") are written as numbers so Excel can compute with them.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Iterable

CSV_CONTENT_TYPE = "text/csv; charset=utf-8"
DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"


def as_number(value):
    """'2.6' -> 2.6, '120' -> 120; text that is not a number, and None, stay as they are."""
    if not isinstance(value, str):
        return value
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return value
    if not number.is_finite():
        return value
    return int(number) if number == number.to_integral_value() else float(number)


def format_cell(value) -> str:
    if value is None or isinstance(value, bool):
        return "" if value is None else ("1" if value else "0")
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.10g}".replace(".", ",")
    if hasattr(value, "to_pydatetime"):  # pandas Timestamp
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.strftime(DATETIME_FORMAT)
    return str(value)


def build_csv(headers: list[str], rows: Iterable[Iterable]) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([format_cell(value) for value in row])
    return buffer.getvalue().encode("utf-8-sig")
