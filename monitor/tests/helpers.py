"""Small builders shared by the tests."""

from datetime import datetime, timedelta

import pandas as pd

from monitor.core.readings import VALUE_COLUMNS

START = datetime(2026, 10, 20, 6, 0, 0)


def make_frame(rows, start=START) -> pd.DataFrame:
    """rows: (minutes_from_start, state, error) tuples; the other columns get fixed values."""
    records = []
    for minutes, state, error in rows:
        records.append(
            {
                "timestamp": start + timedelta(minutes=minutes),
                "state": state,
                "error": error,
                "exhaust_temp": 120.0,
                "boiler_temp": 55.0,
                "oxygen_percent": 9.5,
                "boiler_target_temp": 65.0,
            }
        )
    frame = pd.DataFrame(records, columns=["timestamp", *VALUE_COLUMNS])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def write_csv(path, rows, start=START) -> None:
    """Write rows (minute, state, error) in the exact format of the 4HEAT logger."""
    lines = ["timestamp,30001_state,30002_error,30005_exhaust_temp,30017_boiler_temp,50030_oxygen_percent,20180_boiler_target_temp"]
    for minutes, state, error in rows:
        stamp = (start + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        lines.append(f"{stamp},{state},{error},120,55,9.5,65")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
