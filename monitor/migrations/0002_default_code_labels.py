"""Default names for the state numbers and error codes of the 4HEAT module.

Errors come from the manual (the CSV code N is the display "ErN").
States were deduced from the logs and the module's graph; a "?" marks a weak guess.
Labels already entered in the admin are kept: only missing codes are added.
"""

from django.db import migrations

STATES = {
    1: "Début d'allumage ?",
    3: "Stabilisation",
    5: "En chauffe",
    6: "Modulation",
    7: "Extinction",
    8: "Début d'extinction ?",
    9: "Extinction (variante)",
    10: "Extinction (variante)",
    11: "Extinction anticipée ?",
    30: "Allumage",
    31: "Allumage",
    32: "Allumage",
    33: "Allumage",
}

ERRORS = {
    1: "Thermostat de sécurité HV",
    3: "Arrêt : température des fumées trop faible",
    4: "Surchauffe chaudière",
    5: "Surchauffe des fumées",
    6: "Thermostat pellet",
    7: "Encodeur : pas de signal",
    8: "Encodeur : adaptation du nombre de tours",
    9: "Pression d'eau faible",
    10: "Pression d'eau élevée",
    11: "Horloge temps réel",
    12: "Allumage échoué",
    14: "Interrupteur de pression",
    15: "Manque de tension",
    16: "Communication lambda",
    18: "Manque de pellet",
    22: "Régulateur lambda",
    34: "Dépression sous le seuil minimum",
    35: "Dépression au-dessus du seuil maximal",
}


def add_labels(apps, schema_editor):
    CodeLabel = apps.get_model("monitor", "CodeLabel")
    for kind, names in (("state", STATES), ("error", ERRORS)):
        for code, name in names.items():
            CodeLabel.objects.get_or_create(kind=kind, code=code, defaults={"name": name})


class Migration(migrations.Migration):
    dependencies = [("monitor", "0001_initial")]

    operations = [migrations.RunPython(add_labels, migrations.RunPython.noop)]
