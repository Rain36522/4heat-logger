import django.db.models.deletion
from django.db import migrations, models

import monitor.models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AlertState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("active_code", models.IntegerField(default=0)),
                ("active_since", models.DateTimeField(blank=True, null=True)),
                ("last_seen", models.DateTimeField(blank=True, null=True)),
                ("pending_code", models.IntegerField(blank=True, null=True)),
                ("pending_count", models.PositiveSmallIntegerField(default=0)),
                ("pending_since", models.DateTimeField(blank=True, null=True)),
                ("last_processed", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="CodeLabel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[("state", "État"), ("error", "Défaut")], max_length=8, verbose_name="type"
                    ),
                ),
                ("code", models.PositiveSmallIntegerField(verbose_name="code")),
                ("name", models.CharField(max_length=100, verbose_name="libellé")),
            ],
            options={
                "verbose_name": "libellé de code",
                "verbose_name_plural": "libellés de codes",
                "ordering": ["kind", "code"],
            },
        ),
        migrations.CreateModel(
            name="Parameter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=32, unique=True, verbose_name="code")),
                ("family", models.CharField(db_index=True, default="", editable=False, max_length=8)),
                ("section", models.CharField(blank=True, max_length=100, verbose_name="section")),
                ("description", models.CharField(blank=True, max_length=200, verbose_name="description")),
                ("unit", models.CharField(blank=True, max_length=16, verbose_name="unité")),
                ("state_label", models.CharField(blank=True, max_length=64, verbose_name="état concerné")),
                ("baseline_value", models.CharField(blank=True, max_length=32, verbose_name="valeur de base")),
            ],
            options={
                "verbose_name": "paramètre",
                "verbose_name_plural": "paramètres",
                "ordering": ["code"],
            },
        ),
        migrations.CreateModel(
            name="SettingChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "timestamp",
                    models.DateTimeField(
                        db_index=True, default=monitor.models.now_local, verbose_name="date et heure"
                    ),
                ),
                ("time_is_approximate", models.BooleanField(default=False, verbose_name="heure approximative")),
                ("old_value", models.CharField(blank=True, max_length=32, verbose_name="ancienne valeur")),
                ("new_value", models.CharField(max_length=32, verbose_name="nouvelle valeur")),
                ("comment", models.CharField(blank=True, max_length=300, verbose_name="commentaire")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "parameter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="changes",
                        to="monitor.parameter",
                        verbose_name="paramètre",
                    ),
                ),
            ],
            options={
                "verbose_name": "changement de réglage",
                "verbose_name_plural": "changements de réglages",
                "ordering": ["-timestamp", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="codelabel",
            constraint=models.UniqueConstraint(fields=("kind", "code"), name="unique_kind_code"),
        ),
    ]
