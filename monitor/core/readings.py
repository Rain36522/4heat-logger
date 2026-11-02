"""Read and analyse the CSV written by the 4HEAT logger.

This module has no Django dependency, so it can be tested on its own.
Timestamps are naive local times, exactly as the logger writes them.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pathlib import Path

# CSV column -> short name used everywhere in the app.
COLUMN_MAP = {
    "30001_state": "state",
    "30002_error": "error",
    "30005_exhaust_temp": "exhaust_temp",
    "30017_boiler_temp": "boiler_temp",
    "50030_oxygen_percent": "oxygen_percent",
    "20180_boiler_target_temp": "boiler_target_temp",
}
VALUE_COLUMNS = list(COLUMN_MAP.values())

# A plotted line is cut when two readings are further apart than this.
GAP_BREAK_S = 300
# An error run is split when two readings are further apart than this.
EPISODE_MAX_GAP_S = 600
# A "startup" is the first reading after a pause at least this long
# (the first row of the file counts as a startup too).
STARTUP_GAP_S = 1800

# path -> ((mtime_ns, size), DataFrame). The file is only re-read when it changes.
_cache: dict[str, tuple[tuple[int, int], pd.DataFrame]] = {}


def empty_readings() -> pd.DataFrame:
    frame = pd.DataFrame({"timestamp": pd.Series(dtype="datetime64[ns]")})
    for column in VALUE_COLUMNS:
        frame[column] = pd.Series(dtype="float64")
    return frame


def load_readings(path) -> pd.DataFrame:
    """Return the log as a DataFrame sorted by time (columns: timestamp + VALUE_COLUMNS).

    The result is cached per file version: callers must not modify it in place.
    A missing or empty file gives an empty frame instead of an error.
    """
    file = Path(path)
    try:
        stat = file.stat()
    except OSError:
        return empty_readings()

    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(str(file))
    if cached and cached[0] == signature:
        return cached[1]

    try:
        # The logger may be appending while we read: skip a half-written last line.
        raw = pd.read_csv(file, on_bad_lines="skip")
    except pd.errors.EmptyDataError:
        return empty_readings()

    frame = _normalise(raw)
    _cache[str(file)] = (signature, frame)
    return frame


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.rename(columns=COLUMN_MAP)
    if "timestamp" not in frame:
        return empty_readings()

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"])
    for column in VALUE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce") if column in frame else np.nan

    frame = frame[["timestamp", *VALUE_COLUMNS]]
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return frame.reset_index(drop=True)


def between(frame: pd.DataFrame, start, end) -> pd.DataFrame:
    """Rows with start <= timestamp < end."""
    mask = (frame["timestamp"] >= start) & (frame["timestamp"] < end)
    return frame.loc[mask]


def insert_gap_breaks(frame: pd.DataFrame, max_gap_s: float = GAP_BREAK_S) -> pd.DataFrame:
    """Insert an empty row inside every long gap so plotted lines are cut there.

    Without it a chart would draw a straight line across the nights and weekends
    when the heating is off.
    """
    if len(frame) < 2:
        return frame
    frame = frame.reset_index(drop=True)
    gaps = frame["timestamp"].diff().dt.total_seconds()
    after_gap = gaps[gaps > max_gap_s].index
    if len(after_gap) == 0:
        return frame
    before_gap = after_gap - 1
    breaks = pd.DataFrame({"timestamp": frame.loc[before_gap, "timestamp"] + pd.Timedelta(seconds=1)})
    merged = pd.concat([frame, breaks], ignore_index=True)
    return merged.sort_values("timestamp", kind="stable").reset_index(drop=True)


def find_startups(frame: pd.DataFrame, min_gap_s: float = STARTUP_GAP_S) -> list[pd.Timestamp]:
    """Timestamps of the first reading after each pause of at least min_gap_s."""
    if frame.empty:
        return []
    gaps = frame["timestamp"].diff().dt.total_seconds()
    mask = gaps.isna() | (gaps >= min_gap_s)
    return list(frame.loc[mask, "timestamp"])


def minutes_since_startup(startups: list[pd.Timestamp], moment) -> float | None:
    """Minutes between the latest startup at or before `moment` and `moment`."""
    position = bisect.bisect_right(startups, moment) - 1
    if position < 0:
        return None
    return (moment - startups[position]).total_seconds() / 60


def last_valid(frame: pd.DataFrame, column: str):
    """(value, timestamp) of the last non-empty reading of a column, or (None, None)."""
    valid = frame.dropna(subset=[column])
    if valid.empty:
        return None, None
    row = valid.iloc[-1]
    return float(row[column]), row["timestamp"]


@dataclass(frozen=True)
class ErrorEpisode:
    """An uninterrupted run of readings with the same non-zero error code."""

    code: int
    start: pd.Timestamp
    last_seen: pd.Timestamp
    readings: int
    state: int | None
    minutes_since_startup: float | None

    @property
    def duration_min(self) -> float:
        return (self.last_seen - self.start).total_seconds() / 60


def error_episodes(
    frame: pd.DataFrame,
    startups: list[pd.Timestamp] | None = None,
    max_gap_s: float = EPISODE_MAX_GAP_S,
) -> list[ErrorEpisode]:
    """Group the readings into error episodes (code != 0), oldest first.

    Readings with an empty error value are ignored. A run is cut when the code
    changes or when the logger paused for more than max_gap_s.
    """
    valid = frame.dropna(subset=["error"]).reset_index(drop=True)
    if valid.empty:
        return []
    startups = startups if startups is not None else find_startups(frame)

    codes = valid["error"].astype(int)
    gaps = valid["timestamp"].diff().dt.total_seconds()
    new_run = (codes != codes.shift()) | (gaps > max_gap_s)
    run_id = new_run.cumsum()

    episodes = []
    for _, run in valid.groupby(run_id):
        code = int(run["error"].iloc[0])
        if code == 0:
            continue
        modes = run["state"].dropna().mode()
        start = run["timestamp"].iloc[0]
        episodes.append(
            ErrorEpisode(
                code=code,
                start=start,
                last_seen=run["timestamp"].iloc[-1],
                readings=len(run),
                state=int(modes.iloc[0]) if len(modes) else None,
                minutes_since_startup=minutes_since_startup(startups, start),
            )
        )
    return episodes
