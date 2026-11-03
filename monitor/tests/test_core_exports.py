import math
import unittest
from datetime import datetime

import pandas as pd

from monitor.core.exports import as_number, build_csv, format_cell


class AsNumberTests(unittest.TestCase):
    def test_numbers_stored_as_text_become_numbers(self):
        self.assertEqual(as_number("120"), 120)
        self.assertIsInstance(as_number("120"), int)
        self.assertEqual(as_number("2.6"), 2.6)

    def test_other_values_are_kept(self):
        self.assertEqual(as_number("ON"), "ON")
        self.assertEqual(as_number(""), "")
        self.assertIsNone(as_number(None))


class FormatCellTests(unittest.TestCase):
    def test_numbers_use_a_decimal_comma(self):
        self.assertEqual(format_cell(9.53), "9,53")
        self.assertEqual(format_cell(55.0), "55")
        self.assertEqual(format_cell(42), "42")

    def test_empty_values(self):
        self.assertEqual(format_cell(None), "")
        self.assertEqual(format_cell(math.nan), "")

    def test_dates(self):
        self.assertEqual(format_cell(datetime(2026, 10, 20, 6, 5)), "20.10.2026 06:05:00")
        self.assertEqual(format_cell(pd.Timestamp("2026-10-20 06:05:30")), "20.10.2026 06:05:30")


class BuildCsvTests(unittest.TestCase):
    def test_excel_friendly_layout(self):
        content = build_csv(["Date", "Chaudière"], [(datetime(2026, 10, 20, 6), 55.5), (datetime(2026, 10, 20, 6, 1), math.nan)])
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))  # BOM: Excel reads the accents as UTF-8
        lines = content.decode("utf-8-sig").split("\r\n")
        self.assertEqual(lines[:3], ["Date;Chaudière", "20.10.2026 06:00:00;55,5", "20.10.2026 06:01:00;"])

    def test_text_with_the_separator_is_quoted(self):
        lines = build_csv(["Commentaire"], [("a; b",)]).decode("utf-8-sig").split("\r\n")
        self.assertEqual(lines[1], '"a; b"')
