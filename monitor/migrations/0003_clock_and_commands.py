from django.db import migrations, models

import monitor.models

DAYS = [
    (0, "Lundi"),
    (1, "Mardi"),
    (2, "Mercredi"),
    (3, "Jeudi"),
    (4, "Vendredi"),
    (5, "Samedi"),
    (6, "Dimanche"),
]


class Migration(migrations.Migration):
    dependencies = [("monitor", "0002_default_code_labels")]

    operations = [
        migrations.CreateModel(
            name="ClockState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False, verbose_name="horloge active")),
                ("last_wanted", models.BooleanField(blank=True, null=True)),
                ("failed_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="CommandLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "timestamp",
                    models.DateTimeField(
                        db_index=True, default=monitor.models.now_local, verbose_name="date et heure"
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("web", "Page web"), ("telegram", "Telegram"), ("clock", "Horloge")],
                        max_length=16,
                        verbose_name="origine",
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[("on", "Marche"), ("off", "Arrêt"), ("target", "Consigne chaudière")],
                        max_length=16,
                        verbose_name="commande",
                    ),
                ),
                ("value", models.IntegerField(blank=True, null=True, verbose_name="valeur")),
                ("ok", models.BooleanField(verbose_name="réussie")),
                ("detail", models.CharField(blank=True, max_length=300, verbose_name="détail")),
            ],
            options={
                "verbose_name": "commande envoyée",
                "verbose_name_plural": "commandes envoyées",
                "ordering": ["-timestamp", "-id"],
            },
        ),
        migrations.CreateModel(
            name="DayOff",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("first_day", models.DateField(verbose_name="du")),
                ("last_day", models.DateField(verbose_name="au")),
                ("label", models.CharField(blank=True, max_length=100, verbose_name="motif")),
            ],
            options={
                "verbose_name": "jour de congé",
                "verbose_name_plural": "jours de congé",
                "ordering": ["first_day"],
            },
        ),
        migrations.CreateModel(
            name="ScheduleSlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "start_day",
                    models.PositiveSmallIntegerField(blank=True, choices=DAYS, null=True, verbose_name="jour de début"),
                ),
                ("start_time", models.TimeField(verbose_name="heure de début")),
                (
                    "end_day",
                    models.PositiveSmallIntegerField(blank=True, choices=DAYS, null=True, verbose_name="jour de fin"),
                ),
                ("end_time", models.TimeField(verbose_name="heure de fin")),
            ],
            options={
                "verbose_name": "plage horaire",
                "verbose_name_plural": "plages horaires",
                "ordering": ["start_day", "start_time"],
            },
        ),
    ]
