import unittest
from datetime import datetime, timedelta

from monitor.core.alerts import AlertState, format_duration, format_status, is_status_command, process_readings
from monitor.tests.helpers import START, make_frame


def run(rows, state=None, **kwargs):
    return process_readings(make_frame(rows), state or AlertState(), **kwargs)


class DefectAlertTests(unittest.TestCase):
    def test_one_bad_reading_does_not_alert(self):
        messages, state = run([(0, 5, 0), (1, 5, 12), (2, 5, 0)])
        self.assertEqual(messages, [])
        self.assertEqual(state.active_code, 0)

    def test_a_defect_is_confirmed_after_two_readings_and_reported_once(self):
        rows = [(0, 5, 0), (13, 9, 12), (14, 9, 12), (15, 9, 12), (16, 9, 12)]
        messages, state = run(rows)
        self.assertEqual(len(messages), 1)
        self.assertIn("DÉFAUT chauffage : code 12", messages[0])
        self.assertIn(f"Depuis {START.replace(minute=13):%d.%m %H:%M}", messages[0])
        self.assertIn("13 min après le démarrage", messages[0])
        self.assertEqual(state.active_code, 12)

        # Running again on the same data (or more of the same defect) sends nothing new.
        again, _ = process_readings(make_frame(rows + [(17, 9, 12)]), state)
        self.assertEqual(again, [])

    def test_resolution_message_gives_the_duration(self):
        rows = [(0, 5, 0), (13, 9, 12), (14, 9, 12), (15, 9, 12), (16, 9, 0), (17, 9, 0)]
        messages, state = run(rows)
        self.assertEqual(len(messages), 2)
        self.assertIn("terminé à", messages[1])
        self.assertIn("durée 2 min", messages[1])
        self.assertEqual(state.active_code, 0)

    def test_a_new_code_replaces_the_open_defect(self):
        messages, state = run([(0, 7, 4), (1, 7, 4), (2, 9, 12), (3, 9, 12)])
        self.assertEqual(len(messages), 2)
        self.assertIn("remplace le défaut 4", messages[1])
        self.assertEqual(state.active_code, 12)

    def test_defect_followed_by_a_pause_reports_missing_data(self):
        # Realistic flow: the defect is seen live, then the heating stops and comes back later.
        first, state = run([(0, 9, 12), (1, 9, 12), (2, 9, 12)])
        self.assertEqual(len(first), 1)

        rows = [(0, 9, 12), (1, 9, 12), (2, 9, 12), (600, 31, 0), (601, 31, 0)]
        messages, state = process_readings(make_frame(rows), state)
        self.assertEqual(len(messages), 1)
        self.assertIn("plus de données depuis", messages[0])
        self.assertIn("sans défaut", messages[0])
        self.assertEqual(state.active_code, 0)

    def test_first_run_only_looks_at_the_last_minutes(self):
        old_defect = [(0, 9, 12), (1, 9, 12), (2, 9, 0)]
        recent_ok = [(600 + i, 5, 0) for i in range(5)]
        messages, state = run(old_defect + recent_ok)
        self.assertEqual(messages, [])
        self.assertEqual(state.last_processed, make_frame([(604, 5, 0)])["timestamp"].iloc[0].to_pydatetime())

    def test_names_from_the_labels_are_used(self):
        messages, _ = run([(0, 9, 12), (1, 9, 12)], state_names={9: "Attente"}, error_names={12: "Allumage raté"})
        self.assertIn("code 12 (Allumage raté)", messages[0])
        self.assertIn("État 9 (Attente)", messages[0])

    def test_the_given_state_is_not_modified(self):
        state = AlertState()
        run([(0, 9, 12), (1, 9, 12)], state=state)
        self.assertEqual(state, AlertState())

    def test_empty_error_values_are_skipped(self):
        messages, _ = run([(0, 9, float("nan")), (1, 9, 12), (2, 9, float("nan")), (3, 9, 12)])
        self.assertEqual(len(messages), 1)


class StatusCommandTests(unittest.TestCase):
    def test_status_gives_the_last_reading(self):
        frame = make_frame([(0, 5, 0), (1, 9, 12)])
        text = format_status(frame, START + timedelta(minutes=3), {9: "Attente"}, {12: "Allumage raté"})
        self.assertIn(f"Dernière mesure : {START:%d.%m} 06:01 (il y a 2 min)", text)
        self.assertIn("État 9 (Attente), DÉFAUT code 12 (Allumage raté)", text)
        self.assertIn("Chaudière 55 °C (consigne 65), fumées 120 °C, O₂ 9.5 %", text)
        self.assertNotIn("Plus de données", text)

    def test_status_warns_when_the_data_is_old(self):
        text = format_status(make_frame([(0, 5, 0)]), START + timedelta(hours=2))
        self.assertIn("il y a 2 h", text)
        self.assertIn("aucun défaut", text)
        self.assertIn("Plus de données récentes", text)

    def test_status_without_data(self):
        self.assertEqual(format_status(make_frame([]), START), "Aucune mesure disponible.")

    def test_only_status_from_the_configured_chat_is_accepted(self):
        def update(text, chat=42):
            return {"update_id": 1, "message": {"chat": {"id": chat}, "text": text}}

        self.assertTrue(is_status_command(update("/status"), "42"))
        self.assertTrue(is_status_command(update("/status@MonBot"), "42"))
        self.assertFalse(is_status_command(update("/status", chat=7), "42"))
        self.assertFalse(is_status_command(update("bonjour"), "42"))
        self.assertFalse(is_status_command({"update_id": 2}, "42"))


class FormatDurationTests(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(format_duration(56), "56 min")
        self.assertEqual(format_duration(130), "2 h 10")
        self.assertEqual(format_duration(120), "2 h")


if __name__ == "__main__":
    unittest.main()
