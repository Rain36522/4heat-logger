"""The collector (fourheat_logger) writes the CSV that the app reads: both sides must agree."""

import math
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fourheat_logger.config import Settings
from fourheat_logger.module_client import ModuleError
from fourheat_logger.monitor import Monitor
from fourheat_logger.protocol import parse_values
from fourheat_logger.storage import HEADER, CsvStorage, HeaderMismatchError
from monitor.core import readings as rd

# Shape of a real module answer (ids 3 + 5 digits + value, zero-padded).
ANSWER = (
    '["SEL","0","J30001000000000009","J30002000000000012","J30005000000000188",'
    '"J30017000000000045","J50030000000001459","J20180000000000065","J30038000000000020","J20211000000000001"]'
)
# Header written before the thermostat column was added.
OLD_HEADER = "timestamp,30001_state,30002_error,30005_exhaust_temp,30017_boiler_temp,50030_oxygen_percent,20180_boiler_target_temp"


class CollectorCompatibilityTests(unittest.TestCase):
    def test_csv_header_matches_the_columns_the_app_reads(self):
        self.assertEqual(HEADER, ["timestamp", *rd.COLUMN_MAP])

    def test_a_row_written_by_the_collector_is_read_back_by_the_app(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "4heat_log.csv"
            storage = CsvStorage(path)
            storage.check_header()
            storage.append("2026-11-02T08:05:00", parse_values(ANSWER))

            frame = rd.load_readings(path)

        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        self.assertEqual(str(row["timestamp"]), "2026-11-02 08:05:00")
        self.assertEqual(row["state"], 9)
        self.assertEqual(row["error"], 12)
        self.assertEqual(row["exhaust_temp"], 188)
        self.assertEqual(row["boiler_temp"], 45)
        self.assertEqual(row["oxygen_percent"], 14.59)  # 1459 / 100
        self.assertEqual(row["boiler_target_temp"], 65)
        self.assertEqual(row["thermostat_temp"], 20)

    def test_an_older_csv_gets_the_new_column_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "4heat_log.csv"
            old_content = OLD_HEADER + "\r\n2026-11-02T08:05:00,5,0,188,45,12.56,65\r\n"
            path.write_text(old_content, encoding="utf-8", newline="")
            storage = CsvStorage(path)
            storage.check_header()
            storage.append("2026-11-02T08:06:00", parse_values(ANSWER))

            frame = rd.load_readings(path)
            backup = path.with_name("4heat_log.csv.6cols.bak").read_text(encoding="utf-8")
            header = path.read_text(encoding="utf-8").splitlines()[0]

        self.assertEqual(header, ",".join(HEADER))
        self.assertEqual(backup, old_content.replace("\r\n", "\n"))  # read_text translates newlines
        self.assertEqual(list(frame["boiler_temp"]), [45, 45])
        self.assertTrue(math.isnan(frame["thermostat_temp"].iloc[0]))  # not logged back then
        self.assertEqual(frame["thermostat_temp"].iloc[1], 20)

    def test_a_csv_with_another_header_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "4heat_log.csv"
            path.write_text("timestamp,something_else\n2026-11-02T08:05:00,1\n", encoding="utf-8")
            with self.assertRaises(HeaderMismatchError):
                CsvStorage(path).check_header()

    def test_a_row_is_not_glued_to_a_last_line_without_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "4heat_log.csv"
            # Last line complete but without its line break (copied or edited file).
            path.write_bytes((",".join(HEADER) + "\r\n2026-11-02T08:05:00,5,0,188,45,12.56,65,19").encode())
            CsvStorage(path).append("2026-11-02T08:06:00", parse_values(ANSWER))

            frame = rd.load_readings(path)

        self.assertEqual([str(t) for t in frame["timestamp"]], ["2026-11-02 08:05:00", "2026-11-02 08:06:00"])
        self.assertEqual(list(frame["state"]), [5, 9])


class FussyModule:
    """Behaves like the real module: a query sent right after the TCP test gets an empty answer."""

    def __init__(self, settle_s):
        self._settle_s = settle_s
        self._probed_at = None

    def is_reachable(self):
        self._probed_at = time.monotonic()
        return True

    def read_values(self):
        if self._probed_at is not None and time.monotonic() - self._probed_at < self._settle_s:
            raise ModuleError("no values in answer: ''")
        return parse_values(ANSWER)


class MonitorTests(unittest.TestCase):
    def test_waits_after_the_tcp_test_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "4heat_log.csv"
            settings = Settings(host="module", probe_settle=0.2, output=path)
            monitor = Monitor(settings, FussyModule(settle_s=0.1), CsvStorage(path), threading.Event())

            next_wait = monitor._do_cycle()
            frame = rd.load_readings(path)

        self.assertEqual(next_wait, settings.record_interval)
        self.assertEqual(len(frame), 1)
