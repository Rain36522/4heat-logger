"""Settings of the 4HEAT logger: protocol constants, recorded columns, defaults."""

from dataclasses import dataclass
from pathlib import Path

# Read-all query. This is the only message the logger ever sends to the module.
READ_ALL_QUERY = b'["SEL","0"]'

# Id of the boiler state, used to decide whether the boiler is running.
STATE_ID = "30001"

# Values of STATE_ID meaning "boiler at rest": nothing is recorded in that case.
# EMPTY = filter disabled: every reading is recorded while the module answers.
# Once the rest value is known, put it here, e.g. frozenset({0}).
REST_STATES: frozenset[int] = frozenset({})

# (id, column name, divisor). Order = column order in the CSV.
COLUMNS = [
    ("30001", "state", 1),  # 6 = "Modulation" in the stove tables, not confirmed
    ("30002", "error", 1),  # 0 = none, not checked in the app
    ("30005", "exhaust_temp", 1),  # degC
    ("30017", "boiler_temp", 1),  # degC
    ("50030", "oxygen_percent", 100),  # 1459 -> 14.59 %
    ("20180", "boiler_target_temp", 1),  # degC
    ("30038", "thermostat_temp", 1),  # degC, room thermostat (20 seen on 2026-11-04)
]
# New columns are only ever added at the end: an older CSV is then upgraded in place
# (see CsvStorage.check_header) instead of being refused.


@dataclass(frozen=True)
class Settings:
    """Runtime settings, filled from the command line in main.py."""

    host: str = "192.168.1.182"
    port: int = 80
    probe_timeout: float = 3.0  # seconds, TCP connection test
    probe_settle: float = 3.0  # seconds between the TCP test and the read (see Monitor._do_cycle)
    read_timeout: float = 10.0  # seconds, wait for the module answer
    read_attempts: int = 3  # reads tried before the module is considered unreachable
    retry_delay: float = 5.0  # seconds between two read attempts
    presence_interval: float = 90.0  # seconds between checks while unreachable or at rest
    record_interval: float = 40.0  # seconds between readings while the boiler runs
    output: Path = Path("4heat_log.csv")
