import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import openpyxl

from monitor.core.excel_import import parse_session_date, parse_workbook


def build_workbook(path: Path) -> None:
    """A small copy of the real layout: dates in row 2, one column per session."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Heater_data"
    sheet.append(["Column1", "15.01.26", "23.01.26", "Colonne3", "Colonne4"])
    sheet.append(["Lambda", "15.01.26", "23.01.26", None, datetime(2026, 10, 14)])
    sheet.append(["o03", "1.0", 9, None, 13])  # changed on 23.01 and 14.10
    sheet.append(["Ventilateur 1", None, None, None, None])  # section title
    sheet.append(["UC01", "30", 50, 45, None])  # 45 is in an undated column
    sheet.append(["UC02", "20", "20.0", None, None])  # "changed" to the same value: no change
    sheet.append(["C81", None, None, None, 1])  # first set on 14.10, no baseline
    sheet.append([None, None, None, None, None])  # blank row

    snapshot = workbook.create_sheet("Feuil1")
    for row in [("Lambda", 46309), ("o03", 13), ("UC01", 45), ("UC02", 20), ("C81", 1)]:
        snapshot.append(row)
    workbook.save(path)


class ParseSessionDateTests(unittest.TestCase):
    def test_accepted_formats(self):
        self.assertEqual(parse_session_date("15.01.26"), datetime(2026, 1, 15))
        self.assertEqual(parse_session_date("04.02.2026"), datetime(2026, 2, 4))
        self.assertEqual(parse_session_date(datetime(2026, 10, 14)), datetime(2026, 10, 14))
        self.assertEqual(parse_session_date(46309), datetime(2026, 10, 14))

    def test_missing_or_unreadable_dates(self):
        self.assertIsNone(parse_session_date(None))
        self.assertIsNone(parse_session_date("Colonne3"))


class ParseWorkbookTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "params.xlsx"
        build_workbook(path)
        self.plan = parse_workbook(path)

    def test_parameters_baselines_and_sections(self):
        self.assertEqual(self.plan.baselines, {"o03": "1", "UC01": "30", "UC02": "20", "C81": ""})
        self.assertEqual(self.plan.sections["UC01"], "Ventilateur 1")
        self.assertEqual(self.plan.sections["o03"], "")
        self.assertEqual(self.plan.skipped_rows, ["Ventilateur 1"])
        self.assertEqual(self.plan.baseline_date, datetime(2026, 1, 15))

    def test_dated_changes_are_in_order_with_their_old_values(self):
        summary = [(c.when, c.code, c.old_value, c.new_value) for c in self.plan.changes]
        self.assertEqual(
            summary,
            [
                (datetime(2026, 1, 23), "UC01", "30", "50"),
                (datetime(2026, 1, 23), "o03", "1", "9"),
                (datetime(2026, 10, 14), "C81", "", "1"),
                (datetime(2026, 10, 14), "o03", "9", "13"),
            ],
        )

    def test_undated_column_is_reported_as_pending_with_the_right_old_value(self):
        self.assertEqual([(c.column, c.code, c.old_value, c.new_value) for c in self.plan.pending], [("D", "UC01", "50", "45")])

    def test_snapshot_confirms_the_final_values_once_pending_changes_are_counted(self):
        self.assertEqual(self.plan.snapshot_differences(include_pending=True), [])
        self.assertEqual(self.plan.snapshot_differences(include_pending=False), [("UC01", "50", "45")])


if __name__ == "__main__":
    unittest.main()
