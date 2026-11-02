"""CSV persistence. Each row is flushed and synced to disk right after writing,
so a power cut loses at most the row being written."""

import csv
import os
from pathlib import Path

from .config import COLUMNS
from .protocol import scale

HEADER = ["timestamp"] + [f"{reading_id}_{name}" for reading_id, name, _ in COLUMNS]


class HeaderMismatchError(Exception):
    """The existing CSV file has a different header than the current COLUMNS."""


class CsvStorage:
    def __init__(self, path: Path) -> None:
        self._path = path

    def check_header(self) -> None:
        """Create the parent folder, and refuse a file whose header does not match."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._has_content():
            return
        with self._path.open(newline="", encoding="utf-8") as file:
            existing_header = next(csv.reader(file), [])
        if existing_header != HEADER:
            raise HeaderMismatchError(
                f"{self._path} exists with a different header; use another --output or move it away"
            )

    def append(self, timestamp: str, values: dict[str, int]) -> None:
        row = [timestamp]
        row += [scale(reading_id, values[reading_id]) if reading_id in values else "" for reading_id, _, _ in COLUMNS]

        is_new_file = not self._has_content()
        cut_line = not is_new_file and not self._ends_with_newline()
        with self._path.open("a", newline="", encoding="utf-8") as file:
            if cut_line:
                # Last row cut (power cut, hand edit): start a fresh line instead of gluing to it.
                file.write("\r\n")
            writer = csv.writer(file)
            if is_new_file:
                writer.writerow(HEADER)
            writer.writerow(row)
            file.flush()
            os.fsync(file.fileno())

    def _ends_with_newline(self) -> bool:
        with self._path.open("rb") as file:
            file.seek(-1, os.SEEK_END)
            return file.read(1) == b"\n"

    def _has_content(self) -> bool:
        return self._path.exists() and self._path.stat().st_size > 0
