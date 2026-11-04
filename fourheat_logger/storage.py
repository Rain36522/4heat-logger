"""CSV persistence. Each row is flushed and synced to disk right after writing,
so a power cut loses at most the row being written."""

import csv
import logging
import os
import shutil
from pathlib import Path

from .config import COLUMNS
from .protocol import scale

HEADER = ["timestamp"] + [f"{reading_id}_{name}" for reading_id, name, _ in COLUMNS]

logger = logging.getLogger(__name__)


class HeaderMismatchError(Exception):
    """The existing CSV file has a different header than the current COLUMNS."""


class CsvStorage:
    def __init__(self, path: Path) -> None:
        self._path = path

    def check_header(self) -> None:
        """Create the parent folder, upgrade a file written before columns were added,
        and refuse a file whose header does not match."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._has_content():
            return
        with self._path.open(newline="", encoding="utf-8") as file:
            existing_header = next(csv.reader(file), [])
        if existing_header == HEADER:
            return
        if len(existing_header) < len(HEADER) and HEADER[: len(existing_header)] == existing_header:
            self._add_columns(len(existing_header))
            return
        raise HeaderMismatchError(
            f"{self._path} exists with a different header; use another --output or move it away"
        )

    def _add_columns(self, old_width: int) -> None:
        """Rewrite the file with the new header; old rows get empty cells for the new columns.

        The original is kept next to it (.bak), and the new file replaces it in one step,
        so the app reading the CSV never sees a half-written file.
        """
        backup = self._path.with_name(f"{self._path.name}.{old_width - 1}cols.bak")
        temporary = self._path.with_name(f"{self._path.name}.tmp")
        shutil.copy2(self._path, backup)
        padding = [""] * (len(HEADER) - old_width)
        with self._path.open(newline="", encoding="utf-8") as source, \
                temporary.open("w", newline="", encoding="utf-8") as target:
            reader, writer = csv.reader(source), csv.writer(target)
            next(reader)  # old header
            writer.writerow(HEADER)
            for row in reader:
                if row:
                    writer.writerow(row + padding if len(row) == old_width else row)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, self._path)
        logger.info("%s: added column(s) %s, original kept as %s", self._path, HEADER[old_width:], backup.name)

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
