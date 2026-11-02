"""Tests of the Django layer (models, forms, commands, views).

Run with:  python manage.py test monitor
(the Django-free logic is covered separately by test_core_*.py)
"""

import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from monitor.forms import SettingChangeForm
from monitor.models import AlertState, CodeLabel, Parameter, SettingChange

from .helpers import START, write_csv
from .test_core_excel_import import build_workbook


def make_parameter(code="UC01", baseline="30", **extra):
    return Parameter.objects.create(code=code, baseline_value=baseline, **extra)


class ModelTests(TestCase):
    def test_family_comes_from_the_code_letters(self):
        self.assertEqual(make_parameter("UA01").family, "UA")
        self.assertEqual(make_parameter(" t06 ").code, "t06")

    def test_old_value_is_filled_from_the_previous_change(self):
        parameter = make_parameter()
        first = SettingChange.objects.create(parameter=parameter, timestamp=datetime(2026, 10, 1, 8), new_value="40")
        second = SettingChange.objects.create(parameter=parameter, timestamp=datetime(2026, 10, 2, 8), new_value="45.0")
        self.assertEqual(first.old_value, "30")
        self.assertEqual((second.old_value, second.new_value), ("40", "45"))
        self.assertEqual(parameter.current_value, "45")

    def test_a_change_entered_late_gets_the_value_in_force_at_that_time(self):
        parameter = make_parameter()
        SettingChange.objects.create(parameter=parameter, timestamp=datetime(2026, 10, 5, 8), new_value="50")
        backdated = SettingChange.objects.create(parameter=parameter, timestamp=datetime(2026, 10, 1, 8), new_value="40")
        self.assertEqual(backdated.old_value, "30")

    def test_code_labels(self):
        CodeLabel.objects.all().delete()
        CodeLabel.objects.create(kind=CodeLabel.Kind.ERROR, code=12, name="Surchauffe")
        self.assertEqual(CodeLabel.labels(CodeLabel.Kind.ERROR), {12: "Surchauffe"})
        self.assertEqual(CodeLabel.labels(CodeLabel.Kind.STATE), {})

    def test_default_labels_are_installed_by_the_migrations(self):
        self.assertEqual(CodeLabel.labels(CodeLabel.Kind.ERROR)[12], "Allumage échoué")
        self.assertEqual(CodeLabel.labels(CodeLabel.Kind.STATE)[5], "En chauffe")


class FormTests(TestCase):
    def setUp(self):
        self.parameter = make_parameter("UC01", "30")

    def data(self, **overrides):
        data = {"parameter": "uc01", "new_value": "35,0", "timestamp": "2026-10-20T07:30", "comment": ""}
        data.update(overrides)
        return data

    def test_valid_entry_creates_a_change(self):
        form = SettingChangeForm(self.data())
        self.assertTrue(form.is_valid(), form.errors)
        change = form.save()
        self.assertEqual((change.parameter, change.old_value, change.new_value), (self.parameter, "30", "35"))

    def test_unknown_parameter_is_refused(self):
        self.assertIn("parameter", SettingChangeForm(self.data(parameter="ZZ99")).errors)

    def test_same_value_is_refused(self):
        self.assertIn("new_value", SettingChangeForm(self.data(new_value="30.0")).errors)


class ImportCommandTests(TestCase):
    def run_import(self, *args):
        out = StringIO()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.xlsx"
            build_workbook(path)
            call_command("import_excel", str(path), *args, stdout=out)
        return out.getvalue()

    def test_import_creates_parameters_and_dated_changes(self):
        output = self.run_import()
        self.assertEqual(Parameter.objects.count(), 4)
        self.assertEqual(SettingChange.objects.count(), 4)
        self.assertEqual(Parameter.objects.get(code="UC01").section, "Ventilateur 1")
        self.assertEqual(Parameter.objects.get(code="o03").current_value, "13")
        self.assertTrue(SettingChange.objects.filter(time_is_approximate=False).count() == 0)
        self.assertIn("UC01  50 → 45", output)  # the undated change is listed for manual entry

    def test_import_twice_creates_nothing_new(self):
        self.run_import()
        self.run_import()
        self.assertEqual(SettingChange.objects.count(), 4)
        self.assertEqual(Parameter.objects.count(), 4)

    def test_dry_run_writes_nothing(self):
        self.run_import("--dry-run")
        self.assertEqual(Parameter.objects.count(), 0)


class AlertsCommandTests(TestCase):
    def test_refuses_to_run_without_telegram_settings(self):
        with override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""):
            with self.assertRaises(CommandError):
                call_command("run_alerts", "--once")

    def test_sends_defect_and_resolution_then_remembers_where_it_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "4heat_log.csv"
            rows = [(i, 3, 0) for i in range(3)] + [(i, 3, 12) for i in range(3, 8)] + [(i, 3, 0) for i in range(8, 12)]
            write_csv(csv_path, rows)
            sent = []
            with override_settings(HEATING_CSV_PATH=str(csv_path), TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="c"):
                with mock.patch("monitor.core.alerts.send_telegram", lambda token, chat, text: sent.append(text)):
                    call_command("run_alerts", "--once", stdout=StringIO())
                    first_pass = len(sent)
                    call_command("run_alerts", "--once", stdout=StringIO())
        self.assertEqual(first_pass, 2)  # "DÉFAUT" then "résolu"
        self.assertIn("DÉFAUT", sent[0])
        self.assertEqual(len(sent), 2)  # the second pass found nothing new
        self.assertIsNotNone(AlertState.load().last_processed)

    def test_state_is_not_saved_when_sending_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "4heat_log.csv"
            write_csv(csv_path, [(i, 3, 12) for i in range(6)])
            with override_settings(HEATING_CSV_PATH=str(csv_path), TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="c"):
                with mock.patch("monitor.core.alerts.send_telegram", side_effect=OSError("network down")):
                    with self.assertRaises(OSError):
                        call_command("run_alerts", "--once", stdout=StringIO())
        self.assertIsNone(AlertState.load().last_processed)

    def test_status_command_is_answered_and_acknowledged(self):
        from monitor.management.commands.run_alerts import answer_commands

        updates = [
            {"update_id": 5, "message": {"chat": {"id": 42}, "text": "/status"}},
            {"update_id": 6, "message": {"chat": {"id": 7}, "text": "/status"}},  # someone else: ignored
        ]
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "4heat_log.csv"
            write_csv(csv_path, [(0, 3, 0), (1, 3, 0)])
            sent = []
            with override_settings(HEATING_CSV_PATH=str(csv_path)):
                with mock.patch("monitor.core.alerts.get_telegram_updates", return_value=updates):
                    offset = answer_commands("t", "42", None, 1, sent.append)
        self.assertEqual(offset, 7)
        self.assertEqual(len(sent), 1)
        self.assertIn("Dernière mesure", sent[0])


class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rain", password="secret-pass-123")

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.csv_path = Path(self.folder.name) / "4heat_log.csv"
        rows = [(i, 3, 0) for i in range(30)] + [(i, 3, 4) for i in range(30, 40)] + [(i, 3, 0) for i in range(40, 50)]
        write_csv(self.csv_path, rows)
        settings_override = override_settings(HEATING_CSV_PATH=str(self.csv_path))
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        make_parameter("UC01", "30", description="Ventilateur, puissance")

    def test_pages_require_a_login(self):
        for name in ("status", "timeline", "startups", "faults", "journal"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"])

    def test_all_pages_render_when_logged_in(self):
        self.client.force_login(self.user)
        day = START.date().isoformat()
        for name in ("status", "timeline", "startups", "faults", "journal"):
            response = self.client.get(reverse(name), {"from": day, "to": day})
            self.assertEqual(response.status_code, 200, name)
            # A template comment that leaks into the page (e.g. a multi-line {# #}).
            self.assertNotContains(response, "{#", msg_prefix=name)
        self.assertContains(self.client.get(reverse("faults")), "4")

    def test_pages_render_without_any_data(self):
        self.csv_path.unlink()
        self.client.force_login(self.user)
        for name in ("status", "timeline", "startups", "faults"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_status_page_marks_the_figures_to_refresh(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("status"))
        for block in ("summary", "metrics", "defects", "recent", "changes"):
            self.assertContains(response, f'data-live="{block}"', msg_prefix=block)
        self.assertNotContains(self.client.get(reverse("timeline")), "data-live")

    def test_journal_post_records_a_change(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("journal"),
            {"parameter": "UC01", "new_value": "42", "timestamp": "2026-10-20T07:30", "comment": "test"},
        )
        self.assertRedirects(response, reverse("journal"))
        change = SettingChange.objects.get()
        self.assertEqual((change.old_value, change.new_value), ("30", "42"))

    def test_parameter_info_json(self):
        self.client.force_login(self.user)
        data = self.client.get(reverse("parameter_info", kwargs={"code": "uc01"})).json()
        self.assertEqual((data["code"], data["current_value"]), ("UC01", "30"))
        self.assertEqual(self.client.get(reverse("parameter_info", kwargs={"code": "nope"})).status_code, 404)

    def test_plotly_js_is_served(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("plotly_js"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response["Content-Type"])


class MigrationTests(TestCase):
    def test_models_and_migrations_are_in_sync(self):
        # Fails if a model changed without a migration: run `python manage.py makemigrations monitor`.
        call_command("makemigrations", "--check", "--dry-run", stdout=StringIO())
