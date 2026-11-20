"""CommandLog becomes the command queue (status, attempts...). Commands logged before were
sent right away: they become "done" or "failed", never "pending" (which would send them again)."""

import django.db.models.deletion
from django.db import migrations, models

import monitor.models


def status_from_ok(apps, schema_editor):
    CommandLog = apps.get_model("monitor", "CommandLog")
    for command in CommandLog.objects.all():
        command.status = "done" if command.ok else "failed"
        command.attempts = 1
        command.finished_at = command.timestamp
        command.save(update_fields=["status", "attempts", "finished_at"])


class Migration(migrations.Migration):
    dependencies = [("monitor", "0003_clock_and_commands")]

    operations = [
        migrations.AddField(
            model_name="commandlog",
            name="status",
            field=models.CharField(
                choices=[("pending", "En attente"), ("done", "Faite"), ("failed", "Échec"), ("cancelled", "Remplacée")],
                db_index=True,
                default="pending",
                max_length=16,
                verbose_name="statut",
            ),
        ),
        migrations.AddField(
            model_name="commandlog",
            name="attempts",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="essais"),
        ),
        migrations.AddField(
            model_name="commandlog",
            name="next_try_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="prochain essai"),
        ),
        migrations.AddField(
            model_name="commandlog",
            name="finished_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="terminée le"),
        ),
        migrations.RunPython(status_from_ok, migrations.RunPython.noop),
        migrations.RemoveField(model_name="commandlog", name="ok"),
        migrations.AlterField(
            model_name="commandlog",
            name="timestamp",
            field=models.DateTimeField(
                db_index=True, default=monitor.models.now_local, verbose_name="demandée le"
            ),
        ),
        migrations.AlterModelOptions(
            name="commandlog",
            options={"ordering": ["-timestamp", "-id"], "verbose_name": "commande", "verbose_name_plural": "commandes"},
        ),
        migrations.AddField(
            model_name="clockstate",
            name="command",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="monitor.commandlog",
            ),
        ),
    ]
