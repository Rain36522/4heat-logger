"""Parsing of the 4HEAT module answers and scaling of the recorded values."""

import re

from .config import COLUMNS

_ITEM = re.compile(r"[A-Z]\d{5}\d+")
_DIVISORS = {reading_id: divisor for reading_id, _, divisor in COLUMNS}


def parse_values(raw: str) -> dict[str, int]:
    """Return {id: value} from items such as J30017000000000068.

    If an id is returned several times in one answer (20211 is), the last one wins.
    """
    cleaned = raw.replace("[", "").replace("]", "").replace('"', "").strip()
    values = {}
    for item in cleaned.split(","):
        if _ITEM.fullmatch(item):
            values[item[1:6]] = int(item[6:])
    return values


def scale(reading_id: str, value: int):
    """Apply the divisor of a column (e.g. oxygen / 100); other values stay raw."""
    divisor = _DIVISORS[reading_id]
    return value if divisor == 1 else round(value / divisor, 2)
