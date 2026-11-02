import unittest
from datetime import datetime

from monitor.core.journal import ChangeRecord, current_value, format_value, value_before


class FormatValueTests(unittest.TestCase):
    def test_numbers_are_normalised(self):
        self.assertEqual(format_value("120.0"), "120")
        self.assertEqual(format_value(120.0), "120")
        self.assertEqual(format_value("3,50"), "3.5")
        self.assertEqual(format_value(0), "0")
        self.assertEqual(format_value("0.50"), "0.5")
        self.assertEqual(format_value(" 13 "), "13")

    def test_text_and_empty_values_are_kept(self):
        self.assertEqual(format_value(None), "")
        self.assertEqual(format_value("Delta"), "Delta")
        self.assertEqual(format_value("nan"), "nan")


class ValueRulesTests(unittest.TestCase):
    def setUp(self):
        self.changes = [
            ChangeRecord(1, datetime(2026, 1, 23), "50"),
            ChangeRecord(2, datetime(2026, 2, 4), "35"),
            ChangeRecord(3, datetime(2026, 10, 20, 9, 0), "39"),
        ]

    def test_current_value_is_the_latest_change_or_the_baseline(self):
        self.assertEqual(current_value("39", self.changes), "39")
        self.assertEqual(current_value("30", []), "30")

    def test_current_value_does_not_depend_on_list_order(self):
        self.assertEqual(current_value("30", list(reversed(self.changes))), "39")

    def test_value_before_a_date(self):
        self.assertEqual(value_before("30", self.changes, datetime(2026, 1, 1)), "30")
        self.assertEqual(value_before("30", self.changes, datetime(2026, 3, 1)), "35")
        self.assertEqual(value_before("30", self.changes, datetime(2026, 11, 1)), "39")

    def test_value_before_can_ignore_the_record_being_edited(self):
        self.assertEqual(value_before("30", self.changes, datetime(2026, 11, 1), exclude_pk=3), "35")


if __name__ == "__main__":
    unittest.main()
