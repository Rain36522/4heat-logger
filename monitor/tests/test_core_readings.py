import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from monitor.core import readings as rd
from monitor.tests.helpers import make_frame, write_csv


class LoadReadingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "4heat_log.csv"

    def test_columns_are_renamed_and_rows_sorted_without_duplicates(self):
        write_csv(self.path, [(2, 5, 0), (0, 5, 0), (1, 5, 0), (1, 6, 0)])
        frame = rd.load_readings(self.path)
        self.assertEqual(list(frame.columns), ["timestamp", *rd.VALUE_COLUMNS])
        self.assertEqual(len(frame), 3)
        self.assertTrue(frame["timestamp"].is_monotonic_increasing)
        self.assertEqual(frame["state"].iloc[1], 6)  # the last duplicate wins

    def test_missing_or_empty_file_gives_an_empty_frame(self):
        self.assertTrue(rd.load_readings(self.path).empty)
        self.path.write_text("", encoding="utf-8")
        self.assertTrue(rd.load_readings(self.path).empty)

    def test_empty_values_become_nan(self):
        self.path.write_text(
            "timestamp,30001_state,30002_error,30005_exhaust_temp,30017_boiler_temp,50030_oxygen_percent,20180_boiler_target_temp\n"
            "2026-10-20T06:00:00,9,,120,55,9.5,65\n",
            encoding="utf-8",
        )
        frame = rd.load_readings(self.path)
        self.assertTrue(pd.isna(frame["error"].iloc[0]))
        self.assertEqual(frame["state"].iloc[0], 9)

    def test_cache_is_refreshed_when_the_file_grows(self):
        write_csv(self.path, [(0, 5, 0)])
        self.assertEqual(len(rd.load_readings(self.path)), 1)
        write_csv(self.path, [(0, 5, 0), (1, 5, 0)])
        os.utime(self.path, ns=(10**18, 10**18))  # make sure mtime differs on coarse filesystems
        self.assertEqual(len(rd.load_readings(self.path)), 2)


class GapAndStartupTests(unittest.TestCase):
    def test_gap_break_inserts_one_empty_row_per_gap(self):
        frame = make_frame([(0, 5, 0), (1, 5, 0), (30, 5, 0), (31, 5, 0)])
        broken = rd.insert_gap_breaks(frame)
        self.assertEqual(len(broken), 5)
        empty_rows = broken[broken["state"].isna()]
        self.assertEqual(len(empty_rows), 1)
        self.assertTrue(frame["timestamp"].iloc[1] < empty_rows["timestamp"].iloc[0] < frame["timestamp"].iloc[2])

    def test_no_gap_means_no_change(self):
        frame = make_frame([(0, 5, 0), (1, 5, 0), (2, 5, 0)])
        self.assertEqual(len(rd.insert_gap_breaks(frame)), 3)

    def test_startups_are_the_first_row_and_each_row_after_a_long_pause(self):
        frame = make_frame([(0, 5, 0), (1, 5, 0), (10, 5, 0), (100, 5, 0), (101, 5, 0)])
        startups = rd.find_startups(frame, min_gap_s=1800)
        self.assertEqual(startups, [frame["timestamp"].iloc[0], frame["timestamp"].iloc[3]])

    def test_minutes_since_startup(self):
        frame = make_frame([(0, 5, 0), (100, 5, 0)])
        startups = rd.find_startups(frame)
        moment = frame["timestamp"].iloc[1] + pd.Timedelta(minutes=13)
        self.assertAlmostEqual(rd.minutes_since_startup(startups, moment), 13)
        self.assertIsNone(rd.minutes_since_startup(startups, frame["timestamp"].iloc[0] - pd.Timedelta(minutes=1)))


class ErrorEpisodeTests(unittest.TestCase):
    def test_episodes_group_consecutive_equal_codes(self):
        frame = make_frame(
            [(0, 5, 0), (1, 5, 0), (13, 9, 12), (14, 9, 12), (15, 9, 12), (16, 9, 0), (20, 7, 3), (21, 7, 3)]
        )
        episodes = rd.error_episodes(frame)
        self.assertEqual([(e.code, e.readings, e.state) for e in episodes], [(12, 3, 9), (3, 2, 7)])
        self.assertAlmostEqual(episodes[0].duration_min, 2)
        self.assertAlmostEqual(episodes[0].minutes_since_startup, 13)

    def test_a_pause_splits_an_episode(self):
        frame = make_frame([(0, 9, 12), (1, 9, 12), (30, 9, 12), (31, 9, 12)])
        self.assertEqual(len(rd.error_episodes(frame)), 2)

    def test_readings_without_error_value_are_ignored(self):
        frame = make_frame([(0, 9, 12), (1, 9, float("nan")), (2, 9, 12)])
        episodes = rd.error_episodes(frame)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].readings, 2)

    def test_no_error_gives_no_episode(self):
        self.assertEqual(rd.error_episodes(make_frame([(0, 5, 0), (1, 5, 0)])), [])
        self.assertEqual(rd.error_episodes(rd.empty_readings()), [])

    def test_last_valid_skips_empty_values(self):
        frame = make_frame([(0, 5, 0), (1, float("nan"), 0)])
        value, moment = rd.last_valid(frame, "state")
        self.assertEqual(value, 5)
        self.assertEqual(moment, frame["timestamp"].iloc[0])


if __name__ == "__main__":
    unittest.main()
