"""Import the parameter workbook: parameters, their baseline values and the dated changes.

    python manage.py import_excel /path/to/Liste_Parametres2.xlsx [--dry-run]

Safe to run twice: a change already present (same parameter, date and new value) is skipped.
Columns of the workbook without a date cannot be placed in time; they are listed at the end
so they can be entered by hand in the "Réglages" page with an approximate date.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from monitor.core.excel_import import parse_workbook
from monitor.models import Parameter, SettingChange


class Command(BaseCommand):
    help = "Importe les paramètres et l'historique des réglages depuis le classeur Excel."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Chemin du fichier .xlsx")
        parser.add_argument("--sheet", default="Heater_data", help="Feuille des paramètres (défaut : Heater_data)")
        parser.add_argument(
            "--snapshot-sheet",
            default="Feuil1",
            help="Feuille des valeurs actuelles, pour contrôle (défaut : Feuil1 ; '' pour désactiver)",
        )
        parser.add_argument("--date-row", type=int, default=2, help="Ligne contenant les dates (défaut : 2)")
        parser.add_argument("--dry-run", action="store_true", help="Analyse seulement, n'écrit rien")

    def handle(self, *args, **options):
        try:
            plan = parse_workbook(
                options["path"],
                sheet=options["sheet"],
                snapshot_sheet=options["snapshot_sheet"] or None,
                date_row=options["date_row"],
            )
        except (OSError, KeyError, ValueError) as error:
            raise CommandError(f"Lecture du classeur impossible : {error!r}") from error

        out = self.stdout.write
        out(f"Classeur : {len(plan.baselines)} paramètres, {len(plan.skipped_rows)} titres de section, "
            f"{len(plan.changes)} changements datés, {len(plan.pending)} sans date.")

        if options["dry_run"]:
            out("Mode --dry-run : rien n'est écrit.")
        else:
            created_parameters, created_changes, skipped_changes = self._write(plan)
            out(f"Paramètres créés : {created_parameters} (déjà présents : {len(plan.baselines) - created_parameters})")
            out(f"Changements créés : {created_changes} (déjà présents, ignorés : {skipped_changes})")

        self._report_pending(plan)
        self._report_snapshot(plan)

    @transaction.atomic
    def _write(self, plan):
        parameters = {}
        created_parameters = 0
        for code, baseline in plan.baselines.items():
            parameter, created = Parameter.objects.get_or_create(
                code=code, defaults={"baseline_value": baseline, "section": plan.sections.get(code, "")}
            )
            created_parameters += created
            if not created and not parameter.section and plan.sections.get(code):
                parameter.section = plan.sections[code]
                parameter.save(update_fields=["section"])
            parameters[code] = parameter

        created_changes = skipped_changes = 0
        for planned in plan.changes:
            _, created = SettingChange.objects.get_or_create(
                parameter=parameters[planned.code],
                timestamp=planned.when,
                new_value=planned.new_value,
                defaults={
                    "old_value": planned.old_value,
                    "time_is_approximate": True,  # the sheet only knows the day
                    "comment": f"Import Excel (colonne {planned.column})",
                },
            )
            created_changes += created
            skipped_changes += not created
        return created_parameters, created_changes, skipped_changes

    def _report_pending(self, plan):
        if not plan.pending:
            return
        out = self.stdout.write
        out("")
        out(f"{len(plan.pending)} changements sans date dans le classeur : à saisir à la main dans « Réglages »,")
        out("dans cet ordre (colonne par colonne), avec une date approximative :")
        for planned in plan.pending:
            out(f"  colonne {planned.column} : {planned.code}  {planned.old_value or '∅'} → {planned.new_value}")

    def _report_snapshot(self, plan):
        if not plan.snapshot:
            return
        out = self.stdout.write
        without = plan.snapshot_differences(include_pending=False)
        with_pending = plan.snapshot_differences(include_pending=True)
        out("")
        out(f"Contrôle avec la feuille de valeurs actuelles : {len(without)} écart(s) avec les changements datés seuls, "
            f"{len(with_pending)} écart(s) une fois les changements sans date appliqués.")
        for code, got, expected in with_pending:
            out(f"  {code} : {got} (calculé) ≠ {expected} (feuille)")
