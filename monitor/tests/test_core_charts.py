import json
import unittest

import pandas as pd

from monitor.core import charts
from monitor.core import readings as rd
from monitor.tests.helpers import START, make_frame


def tokens_in(node):
    """Every "$token" string found anywhere in a spec."""
    if isinstance(node, str):
        return {node} if node.startswith("$") else set()
    if isinstance(node, dict):
        return set().union(*(tokens_in(value) for value in node.values())) if node else set()
    if isinstance(node, list):
        return set().union(*(tokens_in(value) for value in node)) if node else set()
    return set()


class TimelineSpecTests(unittest.TestCase):
    def setUp(self):
        self.frame = make_frame([(0, 5, 0), (1, 5, 0), (13, 9, 12), (14, 9, 12), (60, 5, 0), (200, 5, 0)])
        self.episodes = rd.error_episodes(self.frame)
        self.changes = [(START.replace(minute=30), "T06: 120 → 240"), (START.replace(minute=30), "C01: 2,2 → 2,6")]
        self.spec = charts.build_timeline_spec(self.frame, self.episodes, self.changes, {9: "Attente"})

    def test_spec_is_plain_json(self):
        json.dumps(self.spec, allow_nan=False)

    def test_only_known_colour_tokens_are_used(self):
        self.assertLessEqual(tokens_in(self.spec), charts.TOKENS)

    def test_one_band_and_label_per_defect_and_one_line_per_change_time(self):
        shapes = self.spec["layout"]["shapes"]
        self.assertEqual(sum(shape["type"] == "rect" for shape in shapes), 1)
        self.assertEqual(sum(shape["type"] == "line" for shape in shapes), 1)  # two changes, same moment
        self.assertEqual(self.spec["layout"]["annotations"][0]["text"], "⚠ 12")

    def test_changes_at_the_same_moment_share_one_marker(self):
        marker = next(trace for trace in self.spec["data"] if trace["name"] == "Réglage")
        self.assertEqual(len(marker["x"]), 1)
        self.assertEqual(marker["text"][0], "T06: 120 → 240<br>C01: 2,2 → 2,6")

    def test_every_trace_uses_a_declared_axis(self):
        layout = self.spec["layout"]
        for trace in self.spec["data"]:
            key = "yaxis" if trace["yaxis"] == "y" else "yaxis" + trace["yaxis"][1:]
            self.assertIn(key, layout)

    def test_long_gaps_are_cut_with_null_points(self):
        state = next(trace for trace in self.spec["data"] if trace["name"] == "État")
        self.assertGreaterEqual(state["y"].count(None), 1)

    def test_state_names_appear_in_the_hover_text(self):
        state = next(trace for trace in self.spec["data"] if trace["name"] == "État")
        self.assertIn(" — Attente", state["text"])

    def test_thermostat_is_drawn_with_the_temperatures(self):
        frame = self.frame.assign(thermostat_temp=20.0)
        spec = charts.build_timeline_spec(frame, self.episodes, [], {})
        thermostat = next(trace for trace in spec["data"] if trace["name"] == "Thermostat")
        self.assertEqual(thermostat["yaxis"], "y3")
        self.assertIn(20.0, thermostat["y"])

    def test_empty_data_gives_a_message_instead_of_a_chart(self):
        spec = charts.build_timeline_spec(rd.empty_readings(), [], [])
        self.assertEqual(spec["data"], [])
        self.assertIn("Aucune donnée", spec["layout"]["annotations"][0]["text"])


class StartupsSpecTests(unittest.TestCase):
    def setUp(self):
        rows = [(i, 5, 0) for i in range(0, 30)] + [(13 + 100, 9, 12)]
        rows += [(100 + i, 5, 12 if i >= 13 else 0) for i in range(0, 30)]
        self.frame = make_frame(sorted(set(rows)))
        self.startups = rd.find_startups(self.frame)
        self.episodes = rd.error_episodes(self.frame, self.startups)

    def test_one_line_per_startup_aligned_on_zero_and_a_cross_for_the_defect(self):
        spec = charts.build_startups_spec(self.frame, self.startups, self.episodes, "boiler_temp", 45)
        json.dumps(spec, allow_nan=False)
        self.assertLessEqual(tokens_in(spec), charts.TOKENS)
        lines = [trace for trace in spec["data"] if trace["mode"] == "lines"]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(trace["x"][0] == 0 for trace in lines))
        cross = spec["data"][-1]
        self.assertEqual(cross["name"], "Défaut")
        self.assertEqual(cross["x"], [13.0])

    def test_latest_startup_is_drawn_thicker(self):
        spec = charts.build_startups_spec(self.frame, self.startups, [], "state", 45)
        widths = [trace["line"]["width"] for trace in spec["data"]]
        self.assertEqual(widths, [1.5, 3])

    def test_visible_period_keeps_only_the_startups_inside_it(self):
        second = self.startups[1]
        spec = charts.build_startups_spec(
            self.frame, self.startups, self.episodes, "boiler_temp", 45, visible=(second, second + pd.Timedelta(days=1))
        )
        lines = [trace for trace in spec["data"] if trace["mode"] == "lines"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["line"]["width"], 3)  # the only one shown is also the latest

    def test_window_limits_the_points(self):
        spec = charts.build_startups_spec(self.frame, self.startups, [], "boiler_temp", 10)
        self.assertTrue(all(max(trace["x"]) < 10 for trace in spec["data"]))

    def test_no_startup_gives_a_message(self):
        spec = charts.build_startups_spec(rd.empty_readings(), [], [], "boiler_temp", 45)
        self.assertEqual(spec["data"], [])


class DaysSpecTests(unittest.TestCase):
    def setUp(self):
        # Same hours on two consecutive days (START is 06:00).
        rows = [(i, 5, 0) for i in range(0, 20)] + [(24 * 60 + i, 5, 0) for i in range(0, 20)]
        self.frame = make_frame(rows)
        self.days = [START.date(), (START + pd.Timedelta(days=1)).date()]

    def test_each_day_is_drawn_on_the_same_reference_day(self):
        spec = charts.build_days_spec(self.frame, [(day, 0) for day in self.days], "boiler_temp")
        json.dumps(spec, allow_nan=False)
        self.assertLessEqual(tokens_in(spec), charts.TOKENS)
        first, second = spec["data"]
        six_am = charts.DAY_ZERO_MS + 6 * 3_600_000
        self.assertEqual(first["x"][0], six_am)
        self.assertEqual(second["x"][0], six_am)
        self.assertEqual(first["text"][0], "06:00")  # real time kept for the hover
        self.assertEqual([trace["line"]["width"] for trace in spec["data"]], [1.5, 3])

    def test_shift_moves_the_curve_and_is_remembered_for_the_page(self):
        spec = charts.build_days_spec(self.frame, [(self.days[0], 0), (self.days[1], -30)], "boiler_temp")
        second = spec["data"][1]
        self.assertEqual(second["x"][0], charts.DAY_ZERO_MS + (6 * 60 - 30) * 60_000)
        self.assertEqual(second["meta"]["shift"], -30)
        self.assertIn("(-30 min)", second["name"])

    def test_day_without_data_is_skipped_and_no_data_gives_a_message(self):
        empty_day = (START + pd.Timedelta(days=5)).date()
        spec = charts.build_days_spec(self.frame, [(self.days[0], 0), (empty_day, 0)], "boiler_temp")
        self.assertEqual(len(spec["data"]), 1)
        self.assertEqual(charts.build_days_spec(self.frame, [(empty_day, 0)], "boiler_temp")["data"], [])


if __name__ == "__main__":
    unittest.main()
