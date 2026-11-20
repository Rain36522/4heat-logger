"""Parsing of the 4HEAT module answers, scaling of the recorded values, write frames."""

import json
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


def command_item(prefix: str, item_id: str, value: int) -> str:
    """One item of a write frame: J30253 + 1 -> 'J30253000000000001' (value on 12 digits)."""
    if not 0 <= value < 10**12:
        raise ValueError(f"value out of range: {value}")
    return f"{prefix}{item_id}{value:012d}"


def build_command(*items: str) -> bytes:
    """Write frame: ["SEC","<number of items>","<item>",...], without spaces like ["SEL","0"]."""
    return json.dumps(["SEC", str(len(items)), *items], separators=(",", ":")).encode()


def scale(reading_id: str, value: int):
    """Apply the divisor of a column (e.g. oxygen / 100); other values stay raw."""
    divisor = _DIVISORS[reading_id]
    return value if divisor == 1 else round(value / divisor, 2)
