"""How the boiler works, step by step (no Django, so it can be tested on its own).

Source: Saca / Bio4Heating manual, "programmation du chauffage", pages 13 to 23
(operating states and error list), and the parameter descriptions stored in the app.
Nothing here holds a parameter value: values always come from the database.

Texts use a small markup, rendered as chips by the page:
  {T02}        one parameter (chip "T02 180 s")
  {TH06+D01}   a sum: the chips and the result computed with the current values
  @P(UC)       the five power steps of a family (UC03..UC07 = P1..P5; C2 = C23..C27)
A `req` ({"P42": [0], "A13": [1]}) is a settings condition: the transition or sub-step
only applies when every listed parameter currently has one of the listed values.
"""

from __future__ import annotations

import re

# --- parameters ----------------------------------------------------------------------

# Every code of the export of 06.11.2026 (289 parameters).
EXPORT_CODES = tuple(
    """
    A05 A07 A10 A13 A14 A16 A17 A18 A19 A20 A26 A27 A28 A29 A30 A40 A52 A60
    C01 C02 C03 C04 C05 C06 C07 C08 C09 C21 C22 C23 C24 C25 C26 C27 C28 C29 C30
    C43 C44 C45 C46 C47 C63 C64 C65 C66 C67 C81 C82 D01 D08 D10 I10
    IH19 IH21 IH24 IH29 IH30 IH31 IH78 IH80
    P02 P03 P04 P05 P09 P101 P102 P13 P14 P15 P16 P21 P26 P27 P35 P42 P43 P58 P60
    P61 P62 P63 P64 P66 P67 P68 P69 P70 P78 P80 PA21 PA22 PA39 PA41 PA42 PA43
    PR00 PR01 PR02 PR03 PR04 PR05 PR06 PR20 PR21 PR22 PR23 PR24 PR25 PR26 PR70 PR90 S01 S08
    SC01 SC02 SC03 SC04 SC05 SC06 SC07 SC08 SC09 SC43 SC44 SC45 SC46 SC47
    SC63 SC64 SC65 SC66 SC67 SC82
    T01 T02 T03 T04 T05 T06 T07 T08 T09 T10 T11 T13 T14 T15 T16 T17 T18 T22 T23 T24
    T25 T26 T27 T28 T32 T36 T38 T50 T52 T53 T54 T55 T62 T63 T64 T68 T69 T70 T71 T80 T84 T93
    TH01 TH02 TH03 TH06 TH07 TH08 TH09 TH18 TH19 TH20 TH21 TH25 TH26 TH27 TH28 TH30 TH31
    TH35 TH36 TH37 TH38 TH39 TH50 TH51 TH52 TH55 TH56 TH78 TH80
    UA01 UA02 UA03 UA04 UA05 UA06 UA07 UA08 UA09 UA10 UA11 UA41 UA42 UA43 UA44 UA45 UA46
    UA47 UA61 UA62 UA63 UA64 UA65 UA66 UA67 UA82 UA84
    UC01 UC02 UC03 UC04 UC05 UC06 UC07 UC08 UC09 UC10 UC11 UC43 UC44 UC45 UC46 UC47
    UC63 UC64 UC65 UC66 UC67 UC81 UC82
    US01 US02 US03 US04 US05 US06 US07 US08 US09 US10 US11 US43 US44 US45 US46 US47
    US63 US64 US65 US66 US67 US81 US82
    o03 o04 o05 o06 o07 o23 o24 o25 o26 o27
    """.split()
)

# Used in the manual's conditions but absent from the export (no value can be shown).
MISSING_PARAMETERS = {
    "TH24": {
        "label": "Consigne du thermostat chaudière (déduit)",
        "description": "Déduit : IH24 est l'hystérésis du thermostat chaudière et TH26 / TH27 sa plage min / max.",
        "unit": "°C",
    },
    "TH29": {
        "label": "Seuil de température des conditions de thermostat",
        "description": "Utilisé dans les conditions de thermostat. Le libellé de IH29 évoque le thermostat du ballon tampon (non confirmé).",
        "unit": "°C",
    },
}

FAN_NAMES = {"UC": "Ventilateur 1", "US": "Ventilateur 2", "UA": "Ventilateur 3 (extraction)"}
STEP_NAMES = {
    1: "allumage", 2: "stabilisation", 3: "puissance P1", 4: "puissance P2", 5: "puissance P3",
    6: "puissance P4", 7: "puissance P5", 8: "2e allumage", 9: "standby", 10: "extinction", 11: "nettoyage",
}
POWER_NAMES = {3: "P1", 4: "P2", 5: "P3", 6: "P4", 7: "P5"}

# Labels that no rule can build: translations of the descriptions stored in the app.
LABELS = {
    "A05": "Gestion de la puissance de combustion : 0 = manuelle, 1 = proportionnelle (à la température de l'eau)",
    "A07": "Entrée thermostat d'ambiance : 0 = désactivée, 1 = passage de Normal en Standby, 2 = blocage de la pompe, "
           "3 = marche / arrêt de la chaudière, 4 = passage de Normal en Modulation",
    "A10": "Depuis l'extinction : 0 = pas de passage direct à l'allumage, 1 = passage direct à la vérification possible",
    "A13": "Thermostat chaudière atteint : 0 = Modulation, 1 = Modulation puis Standby si chaudière > TH24 + D10 pendant T55",
    "A14": "Gestion de l'erreur du capteur de pression : 0 = désactivée, 1 = activée",
    "A16": "Délai de changement de puissance : 0 = désactivé, 1 = activé",
    "A17": "Vitesse du ventilateur 1 porte ouverte : 0 = vitesse 0, 1 = vitesse max",
    "A18": "Vitesse du ventilateur 2 porte ouverte : 0 = vitesse 0, 1 = vitesse max",
    "A19": "Vitesse du ventilateur 3 porte ouverte : 0 = vitesse 0, 1 = vitesse max",
    "A20": "Configuration du capteur de pression d'eau : 0 = type A, 1 = type B, 2 = type C",
    "A26": "Sortie du Standby : 0 = dès que les conditions disparaissent, 1 = dès que les conditions disparaissent, "
           "à la fin de T13 et si fumées < T28 (seulement si A27 = 1 ; « T28 » tel qu'écrit dans le manuel)",
    "A27": "Extinction en Standby : 0 = désactivée (temps T32 et T26 utilisés), 1 = activée (paramètres TH28 et T13 utilisés)",
    "A28": "Frein de vis : 0 = désactivé, 1 = activé",
    "A29": "Sortie du Standby sur demande d'eau sanitaire : 0 = désactivée, 1 = activée",
    "A30": "Régulateur de dépression sur la vitesse du ventilateur d'extraction : 0 = désactivé, 1 = activé",
    "A40": "Extinction automatique : 0 = désactivée, 1 = activée",
    "A52": "Thermostat d'ambiance à distance : 0 = désactivé, 1 = Normal / Standby, 2 = blocage de la pompe, "
           "3 = désactivé, 4 = Normal / Modulation",
    "A60": "Fonction sanitaire : 0 = seulement avec détecteur de débit (P35 = 0, 1, 5), 1 = avec P35 = 0, 1, 2, 3, 5",
    "C81": "Pas de régulation de la vis : 0,1 à 99,0 s si P21 < 2, 1 à 99 % si P21 = 2",
    "D01": "Écart de température pour sortir de la stabilisation",
    "D08": "Écart de température pour la modulation de puissance en gestion proportionnelle",
    "D10": "Écart de température pour passer de Modulation en Standby",
    "IH19": "Hystérésis du thermostat d'activation de l'échangeur",
    "IH21": "Écart sanitaire sur le thermostat TH21",
    "IH24": "Hystérésis du thermostat chaudière",
    "IH29": "Hystérésis du thermostat du ballon tampon",
    "IH30": "Hystérésis du thermostat différentiel",
    "IH31": "Hystérésis du thermostat de la sortie auxiliaire",
    "IH78": "Hystérésis du thermostat de la sonde de sécurité",
    "IH80": "Hystérésis du thermostat d'activation du moteur de nettoyage 2",
    "P02": "Nombre maximal de tentatives d'allumage (ensuite, la chaudière passe en Bloc)",
    "P03": "Nombre de puissances de fonctionnement",
    "P04": "Numéro de recette",
    "P05": "Période de la vis 1",
    "P09": "Configuration du capteur de niveau de pellets (voir 3.4.9)",
    "P101": "Configuration DAC0 : 0 = non utilisé, 1 = vis, 2 = ventilateur 1",
    "P102": "Configuration DAC1 : 0 = non utilisé, 1 = vis, 2 = ventilateur 3",
    "P13": "Période de la vis 2",
    "P14": "Vitesse minimale du ventilateur 1",
    "P15": "Pas de correction de l'étalonnage de la vis",
    "P16": "Pas de correction de l'étalonnage du ventilateur 1",
    "P21": "Gestion de la vis : 0 = pause-travail, 1 = variateur, 2 = variateur en pause-travail",
    "P26": "Vitesse minimale du ventilateur 2",
    "P27": "Vitesse minimale du ventilateur 3",
    "P35": "Configuration hydraulique",
    "P42": "Chaudière à air : 0 = chaudière hydro, 1 = chaudière à air",
    "P43": "Configuration de la vis 2 : 0 = absente, 1 = comme la vis 1, 2 = indépendante et OFF pendant le préchargement, "
           "3 = indépendante et ON pendant le préchargement",
    "P58": "Activation du régulateur lambda",
    "P60": "Gestion des erreurs du régulateur lambda",
    "P61": "Configuration de la sortie OUT1 (voir 11.5)",
    "P62": "Configuration de la sortie OUT2 (voir 11.5)",
    "P63": "Configuration de la sortie OUT3 (voir 11.5)",
    "P64": "Configuration de la sortie OUT4 (voir 11.5)",
    "P66": "Configuration RS485 : 0 = gestion du module lambda désactivée, 1 = activée (voir 11.9)",
    "P67": "Sens de régulation du ventilateur 1",
    "P68": "Sens de régulation du ventilateur 2",
    "P69": "Sens de régulation de la vis",
    "P70": "Gestion de la régulation des sorties",
    "P78": "Configuration de la sonde de sécurité : 0 = désactivée, 1 = activée",
    "P80": "Configuration du moteur de nettoyage 2",
    "PA21": "Gestion des ventilateurs pour le moteur de nettoyage 1",
    "PA22": "Gestion des ventilateurs pour le moteur de nettoyage 2",
    "PA39": "Configuration de la sonde chaudière : 0 = NTC10K, 1 = NTC100K",
    "PA41": "Configuration de la sécurité moteur 1 : 0 = absente, 1 = signalisation seule, 2 = Bloc, 3 = extinction puis Bloc définitif",
    "PA42": "Configuration de la sécurité moteur 2 : 0 = absente, 1 = signalisation seule, 2 = Bloc, 3 = extinction puis Bloc définitif",
    "PA43": "Configuration de la sécurité moteur 3 : 0 = absente, 1 = signalisation seule, 2 = Bloc, 3 = extinction puis Bloc définitif",
    "PR70": "Seuil d'alarme de dépression minimale",
    "PR90": "Seuil d'alarme de dépression maximale",
    "S01": "Seuil minimal du capteur de pression",
    "S08": "Seuil maximal du capteur de pression",
    "T01": "Durée du nettoyage de vérification (check-up)",
    "T02": "Durée du préchauffage",
    "T03": "Durée du préchargement de la vis",
    "T04": "Durée de l'allumage fixe",
    "T05": "Durée de l'allumage variable",
    "T06": "Durée de la stabilisation",
    "T07": "Intervalle entre deux nettoyages périodiques",
    "T08": "Durée du nettoyage périodique",
    "T09": "Délai haute tension 1 (thermostat de sécurité)",
    "T10": "Délai haute tension 2 (pressostat)",
    "T11": "Délai de sortie du Standby",
    "T13": "Durée minimale de l'extinction en Standby",
    "T14": "Durée de la pré-extinction",
    "T15": "Durée de l'extinction en sécurité",
    "T16": "Durée du nettoyage final",
    "T17": "Délai de changement de puissance",
    "T18": "Délai de changement de puissance depuis l'allumage",
    "T22": "Délai d'entrée en Standby",
    "T23": "Temps de remplissage du réservoir à pellets au-dessus du niveau minimal",
    "T24": "Temps de remplissage du réservoir à pellets pour atteindre le niveau minimal",
    "T25": "Délai du capteur de pellets pour signaler la présence de pellets",
    "T26": "Délai du capteur de pellets pour signaler le manque de pellets",
    "T27": "Temps d'arrêt du moteur de nettoyage 1",
    "T28": "Temps de marche du moteur de nettoyage 1",
    "T32": "Durée d'arrêt du système en Standby",
    "T36": "Durée de marche du système en Standby",
    "T38": "Délai de l'alarme du thermostat pellet",
    "T50": "Durée d'ouverture de la vanne de sécurité",
    "T52": "Temps d'arrêt du moteur de nettoyage 2",
    "T53": "Temps de marche du moteur de nettoyage 2",
    "T54": "Marche du moteur de nettoyage 2 à la fin de l'extinction / de la vérification",
    "T55": "Temps d'attente avant de passer de Modulation en Standby",
    "T62": "Intervalle de surveillance de l'oxygène",
    "T63": "Durée maximale du régulateur hors plage",
    "T64": "Délai avant la première régulation",
    "T68": "Délai de sortie de la fonction sanitaire",
    "T69": "Période du régulateur",
    "T70": "Temps d'attente avant la première régulation",
    "T71": "Minuterie du message de nettoyage",
    "T80": "Délai avant l'alarme de dépression",
    "T84": "Temps de fonctionnement avant l'arrêt automatique du système",
    "T93": "Délai de la sécurité haute tension 3",
    "TH01": "Seuil « poêle éteint »",
    "TH02": "Arrêt de la résistance d'allumage (bougie)",
    "TH03": "Thermostat de pré-extinction pour fumées trop froides",
    "TH06": "Seuil pour passer en stabilisation",
    "TH07": "Seuil de modulation des fumées",
    "TH08": "Sécurité des fumées",
    "TH09": "Seuil de fumées pour passer directement en Normal",
    "TH18": "Thermostat antigel",
    "TH19": "Thermostat d'activation de l'échangeur",
    "TH20": "Thermostat sanitaire minimal",
    "TH21": "Thermostat sanitaire maximal",
    "TH25": "Thermostat de sécurité de la chaudière",
    "TH26": "Plage du thermostat chaudière : minimum",
    "TH27": "Plage du thermostat chaudière : maximum",
    "TH28": "Température des fumées pour l'extinction en Standby",
    "TH30": "Thermostat différentiel",
    "TH31": "Thermostat de la sortie auxiliaire",
    "TH50": "Consigne du thermostat d'activation lambda",
    "TH51": "Minimum du thermostat d'activation lambda",
    "TH52": "Maximum du thermostat d'activation lambda",
    "TH55": "Plage du thermostat du ballon tampon : minimum",
    "TH56": "Plage du thermostat du ballon tampon : maximum",
    "TH78": "Thermostat de la sonde de sécurité",
    "TH80": "Thermostat d'activation du moteur de nettoyage 2",
    "UA84": "Pas de régulation du ventilateur d'extraction",
    "UC81": "Pas de régulation du ventilateur 1",
    "US81": "Pas de régulation du ventilateur 2",
}

# What a parameter changes, only when the manual or the parameter description says so.
IMPACTS = {
    "A05": "À 1, la puissance (P1 à P5) suit la température de l'eau sur une plage D08.",
    "A07": "Valeur 4 : passages Normal ⇄ Modulation par thermostat ; valeur 1 : passages vers Standby par thermostat "
           "(conditions décrites pour P42 = 0).",
    "A13": "À 0, la chaudière reste en Modulation ; à 1, elle passe ensuite en Standby si la chaudière dépasse "
           "TH24 + D10 pendant T55.",
    "A14": "À 0, les erreurs de pression d'eau (Er09, Er10) ne sont pas gérées.",
    "A27": "Choisit le type de Standby : 1 = avec arrêt (attente T13, arrêt, nettoyage final T16, OFF) ; "
           "0 = sans arrêt (alternance OFF pendant T32 et ON pendant T36).",
    "A52": "Valeur 4 : passages Normal ⇄ Modulation par le thermostat à distance ; valeur 1 : passages vers Standby "
           "(conditions décrites pour P42 = 0).",
    "D01": "En stabilisation, passage en Normal dès que les fumées dépassent TH06 + D01.",
    "D08": "Écart de température sur lequel se répartissent les puissances en gestion proportionnelle (A05 = 1).",
    "D10": "Avec A13 = 1, la chaudière doit dépasser TH24 + D10 pendant T55 pour passer de Modulation en Standby.",
    "P02": "À la fin de T05 ou de T06 avec des fumées sous TH06 : nouvelle tentative d'allumage tant qu'il en reste, "
           "sinon arrêt avec erreur Er12.",
    "P35": "Choisit quelles conditions de thermostat s'appliquent (P35 = 0, 1, 5 / 2, 3 / 4).",
    "P42": "Toutes les conditions de passage par thermostat vers Modulation et Standby sont décrites pour P42 = 0 (hydro).",
    "P43": "Au préchargement, la vis 2 est ON si P43 = 3 et OFF si P43 = 2.",
    "P78": "À 1, la sonde de sécurité peut déclencher la Sécurité (seuil TH78).",
    "T01": "Durée de la vérification ; à la fin, la chaudière passe à l'allumage.",
    "T02": "Durée du préchauffage (1re sous-étape de l'allumage).",
    "T03": "Durée du préchargement (2e sous-étape de l'allumage).",
    "T04": "Durée de l'allumage fixe (3e sous-étape de l'allumage).",
    "T05": "Durée de l'allumage variable ; à la fin, les fumées sont comparées à TH06.",
    "T06": "Durée de la stabilisation ; à la fin, des fumées sous TH06 entraînent une nouvelle tentative ou l'arrêt Er12.",
    "T11": "Délai avant le retour à l'état précédent quand la condition de Standby disparaît.",
    "T13": "Standby avec arrêt (A27 = 1) : durée de l'attente avant l'arrêt.",
    "T14": "Si la condition de fin de combustion n'a pas disparu à la fin de T14 : arrêt avec erreur Er03.",
    "T15": "Temps laissé pour redescendre sous les seuils de sécurité avant l'arrêt avec erreur Er04 / Er05.",
    "T16": "Durée du nettoyage final (Arrêt, Reprise d'allumage, Standby avec arrêt).",
    "T22": "Délai avant l'entrée en Standby depuis Normal ou Modulation.",
    "T32": "Standby sans arrêt (A27 = 0) : durée de la phase OFF.",
    "T36": "Standby sans arrêt (A27 = 0) : durée de la phase ON.",
    "T55": "Modulation – Attente (A13 = 1) : temps pendant lequel la chaudière doit rester au-dessus de TH24 + D10 "
           "avant de passer en Standby.",
    "TH01": "Fumées au-dessus : la chaudière reste en refroidissement (Arrêt, Reprise d'allumage) ; en dessous : "
            "nettoyage final. Depuis OFF, fumées > TH01 → Arrêt. En Bloc, ventilateurs en marche tant que fumées > TH01.",
    "TH02": "La bougie reste allumée tant que les fumées sont sous ce seuil (allumage variable, stabilisation).",
    "TH03": "En Normal, à la puissance finale, des fumées sous ce seuil déclenchent la pré-extinction.",
    "TH06": "Fin de l'allumage variable : fumées > TH06 → stabilisation, sinon nouvelle tentative ou arrêt Er12. "
            "Fin de la stabilisation : fumées < TH06 → nouvelle tentative ou arrêt Er12.",
    "TH07": "En Normal, fumées > TH07 → Modulation ; en Modulation, retour en Normal quand fumées < TH07 et chaudière < TH24.",
    "TH08": "Fumées au-dessus de ce seuil → Sécurité (depuis Normal, Modulation et Standby).",
    "TH09": "Si les fumées dépassent ce seuil pendant la vérification, l'allumage ou la stabilisation, la chaudière "
            "passe directement en Normal.",
    "TH25": "Chaudière au-dessus de ce seuil → Sécurité ; depuis OFF, eau > TH25 → Bloc.",
    "TH28": "Standby avec arrêt (A27 = 1) : fumées > TH28 → reste en arrêt ; fumées < TH28 → nettoyage final puis OFF.",
    "TH78": "Sonde de sécurité au-dessus de ce seuil → Sécurité (si P78 = 1).",
}

CONSTRAINTS = {
    "D08": {
        "multiple_of": 4,
        "text": "Multiple de 4",
        "hint": "Hypothèse : probablement 4 paliers entre P1 et P5 (non confirmé).",
    },
}


def _family(code: str) -> tuple[str, int | None]:
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", code)
    return (match.group(1), int(match.group(2))) if match else (code, None)


def label_for(code: str) -> str:
    """French label: by rule for the families sharing one numbering, else from LABELS."""
    if code in LABELS:
        return LABELS[code]
    if code in MISSING_PARAMETERS:
        return MISSING_PARAMETERS[code]["label"]
    prefix, number = _family(code)
    if number is None:
        return ""
    if prefix in FAN_NAMES:
        fan = FAN_NAMES[prefix]
        if number in STEP_NAMES:
            return f"{fan} – {STEP_NAMES[number]}"
        if prefix == "UA" and 41 <= number <= 47:
            return f"{fan} – vitesse min. du régulateur de dépression – {_regulated_step(number - 40)}"
        if prefix == "UA" and 61 <= number <= 67:
            return f"{fan} – vitesse max. du régulateur de dépression – {_regulated_step(number - 60)}"
        if 43 <= number <= 47:
            return f"{fan} – vitesse min. du régulateur lambda – {POWER_NAMES[number - 40]}"
        if 63 <= number <= 67:
            return f"{fan} – vitesse max. du régulateur lambda – {POWER_NAMES[number - 60]}"
        if number == 82:
            return f"{fan} – puissance thermostat pellet"
    if prefix in ("C", "SC"):
        what = "Vis 1" if prefix == "C" else "Vitesse de la vis (variateur)"
        if prefix == "C" and 21 <= number <= 30:
            return f"Vis 2 – {STEP_NAMES[number - 20]}"
        if number in STEP_NAMES:
            return f"{what} – {STEP_NAMES[number]}"
        if 43 <= number <= 47:
            return f"{what} – vitesse min. du régulateur lambda – {POWER_NAMES[number - 40]}"
        if 63 <= number <= 67:
            return f"{what} – vitesse max. du régulateur lambda – {POWER_NAMES[number - 60]}"
        if number == 82:
            return f"{what} – puissance thermostat pellet"
    if prefix == "TH" and 35 <= number <= 39:
        return f"Thermostat d'extinction – puissance {POWER_NAMES[number - 32]}"
    if prefix == "PR" and number <= 6:
        return f"Consigne du régulateur de dépression – {_regulated_step(number + 1)}"
    if prefix == "PR" and 20 <= number <= 26:
        return f"Écart du régulateur de dépression – {_regulated_step(number - 19)}"
    if prefix == "o" and 3 <= number <= 7:
        return f"Niveau d'oxygène – puissance {POWER_NAMES[number]}"
    if prefix == "o" and 23 <= number <= 27:
        return f"Plage d'oxygène – puissance {POWER_NAMES[number - 20]}"
    return ""


def _regulated_step(position: int) -> str:
    """1 = allumage, 2 = stabilisation, 3..7 = P1..P5 (numbering of the regulator parameters)."""
    return STEP_NAMES[position]


def impact_for(code: str) -> str:
    if code in IMPACTS:
        return IMPACTS[code]
    prefix, number = _family(code)
    if prefix == "TH" and number is not None and 35 <= number <= 39:
        power = POWER_NAMES[number - 32]
        return f"En Normal à la puissance {power}, des fumées sous ce seuil déclenchent la pré-extinction."
    return ""


# --- operating cycle ----------------------------------------------------------------

FAMILIES = {
    "start": "Démarrage",
    "run": "Régime",
    "standby": "Veille",
    "stop": "Arrêt",
    "danger": "Danger",
}

OFF = "OFF"
SAFETY_EXITS = [
    {"when": "", "condition": "fumées > {TH08}", "target": "safety"},
    {"when": "", "condition": "chaudière > {TH25}", "target": "safety"},
    {"when": "", "condition": "sonde de sécurité > {TH78}", "target": "safety", "req": {"P78": [1]}},
]


def _thermostat_cases(target: str, a07: int, a52: int, closed: bool = False) -> list[dict]:
    """The four thermostat transitions of pages 17 to 20 (all written for P42 = 0, hydro boiler)."""
    state = "fermé" if closed else "ouvert"
    joiner = " ou " if closed else " et "
    boiler = "chaudière < {TH29}" if closed else "chaudière > {TH29}"
    tail = " (et fumées < {TH07} et chaudière < {TH24})" if closed else ""
    return [
        {"when": "", "target": target, "req": {"A07": [a07], "P35": [0, 1, 5], "P42": [0]},
         "condition": f"thermostat d'ambiance {state}{joiner}commutateur d'écoulement {state}{tail}"},
        {"when": "", "target": target, "req": {"A07": [a07], "P35": [2, 3], "P42": [0]},
         "condition": f"thermostat d'ambiance {state}{joiner}{boiler} et fonctionnement hiver{tail}"},
        {"when": "", "target": target, "req": {"A52": [a52], "P35": [0, 1, 5], "P42": [0]},
         "condition": ("température ambiante < consigne du clavier à distance" if closed else
                       "température ambiante > consigne du clavier à distance")
                      + f", thermostat à distance{' activé ou' if closed else ' ouvert et'} interrupteur de débit {state}{tail}"},
        {"when": "", "target": target, "req": {"A52": [a52], "P35": [2, 3], "P42": [0]},
         "condition": ("température ambiante < consigne du clavier à distance" if closed else
                       "température ambiante > consigne du clavier à distance")
                      + f", thermostat à distance activé{joiner}{boiler} et fonctionnement hiver{tail}"},
    ]


STANDBY_ENTRIES = _thermostat_cases("standby", a07=1, a52=1) + [
    {"when": "", "target": "standby", "req": {"P35": [2, 3], "P42": [0]},
     "condition": "chaudière > {TH29} et mode été"},
    {"when": "", "target": "standby", "req": {"P35": [4], "P42": [0]}, "condition": "chaudière > {TH29}"},
]
for _entry in STANDBY_ENTRIES:
    _entry["note"] = "après {T22}"

POWER_ORGANS = {
    "fans": ["@P(UC)", "@P(US)", "@P(UA)"], "auger1": "@P(C)", "auger2": "@P(C2)", "plug": OFF,
}

STAGES = [
    {
        "id": "off", "name": "OFF", "family": "stop",
        "summary": "La chaudière est à l'arrêt : ventilateurs, vis et bougie sont coupés. Elle surveille seulement "
                   "les températures des fumées et de l'eau.",
        "substeps": [{"name": "OFF", "fans": [OFF, OFF, OFF], "auger1": OFF, "auger2": OFF, "plug": OFF}],
        "transitions": [
            {"when": "", "condition": "fumées > {TH01}", "target": "shutdown"},
            {"when": "", "condition": "eau > {TH25}", "target": "block"},
        ],
        "notes": ["Le passage de OFF à la vérification, à la demande de démarrage, n'est pas détaillé dans le document."],
    },
    {
        "id": "check", "name": "Vérification", "family": "start",
        "summary": "Avant d'allumer, la chaudière ventile le foyer à vitesse maximale pendant un temps fixe, "
                   "sans pellets ni bougie.",
        "substeps": [{"name": "Vérification (check-up)", "duration": "{T01}",
                      "fans": ["vitesse max", "vitesse max", "vitesse max"], "auger1": OFF,
                      "auger2": "–", "plug": OFF}],
        "notes": ["La case « vis sans fin 2 » est vide dans le document."],
        "transitions": [
            {"when": "", "condition": "fumées > {TH09}", "target": "normal"},
            {"when": "fin de {T01}", "condition": "", "target": "ignition"},
        ],
    },
    {
        "id": "ignition", "name": "Allumage", "family": "start",
        "summary": "La bougie chauffe, puis les vis amènent les pellets par étapes jusqu'à ce que le feu prenne. "
                   "Si les fumées sont assez chaudes à la fin, la chaudière passe en stabilisation ; sinon elle "
                   "retente un allumage ou s'arrête en erreur.",
        "notes": ["Au 1er allumage variable, les ventilateurs UC01 / US01 / UA01 sont supposés : le document cite "
                  "« I Allumage » avec les valeurs du 2e allumage."],
        "substeps": [
            {"name": "Préchauffage (« Épuisement » dans le document)", "short": "Préchauffage", "duration": "{T02}",
             "fans": ["{UC01}", "{US01}", "{UA01}"], "auger1": OFF, "auger2": OFF, "plug": "ON"},
            {"name": "Préchargement", "duration": "{T03}", "fans": ["{UC01}", "{US01}", "{UA01}"],
             "auger1": "ON (continu)",
             "auger2": [{"value": "ON", "req": {"P43": [3]}}, {"value": "OFF", "req": {"P43": [2]}}],
             "plug": "ON"},
            {"name": "Allumage fixe", "duration": "{T04}", "fans": ["{UC01}", "{US01}", "{UA01}"],
             "auger1": "{C01}", "auger2": "{C21}", "plug": "ON"},
            {"name": "Allumage variable", "duration": "{T05}",
             "fans": [
                 [{"label": "1er", "value": "{UC01}"}, {"label": "2e", "value": "{UC08}"}],
                 [{"label": "1er", "value": "{US01}"}, {"label": "2e", "value": "{US08}"}],
                 [{"label": "1er", "value": "{UA01}"}, {"label": "2e", "value": "{UA08}"}],
             ],
             "auger1": [{"label": "1er", "value": "{C01}"}, {"label": "2e", "value": "{C08}"}],
             "auger2": [{"label": "1er", "value": "{C21}"}, {"label": "2e", "value": "{C28}"}],
             "plug": "ON tant que fumées < {TH02}"},
        ],
        "transitions": [
            {"when": "à tout moment", "condition": "fumées > {TH09}", "target": "normal"},
            {"when": "fin de {T02}", "condition": "", "target": "ignition", "sub": "Préchargement"},
            {"when": "fin de {T03}", "condition": "", "target": "ignition", "sub": "Allumage fixe"},
            {"when": "fin de {T04}", "condition": "", "target": "ignition", "sub": "Allumage variable"},
            {"when": "fin de {T05}", "condition": "fumées > {TH06}", "target": "stabilisation"},
            {"when": "fin de {T05}", "condition": "fumées < {TH06} et tentatives > 0 et ≤ {P02}",
             "target": "ignition", "sub": "2e allumage variable"},
            {"when": "fin de {T05}", "condition": "fumées < {TH06} et tentatives épuisées",
             "target": "shutdown", "error": "Er12"},
        ],
    },
    {
        "id": "stabilisation", "name": "Stabilisation", "family": "start",
        "summary": "Le feu a pris : la chaudière l'entretient avec des réglages modérés pour qu'il se stabilise, "
                   "avant de passer en fonctionnement normal.",
        "substeps": [{"name": "Stabilisation", "duration": "{T06}", "fans": ["{UC02}", "{US02}", "{UA02}"],
                      "auger1": "{C02}", "auger2": "{C22}",
                      "plug": "ON si fumées < {TH02}"}],
        "transitions": [
            {"when": "avant la fin de {T06}", "condition": "fumées > {TH09}", "target": "normal"},
            {"when": "avant la fin de {T06}", "condition": "fumées > {TH06+D01}", "target": "normal"},
            {"when": "fin de {T06}", "condition": "fumées < {TH06} et tentatives > 0 et ≤ {P02}",
             "target": "ignition", "sub": "2e allumage variable"},
            {"when": "fin de {T06}", "condition": "fumées < {TH06} et tentatives épuisées",
             "target": "shutdown", "error": "Er12"},
        ],
        "notes": ["Le cas « fin de T06 avec des fumées entre TH06 et TH06 + D01 » n'est pas décrit dans le document.",
                  "Le seuil de la bougie est coupé dans le document (« TH0… ») ; supposé TH02."],
    },
    {
        "id": "relight", "name": "Reprise d'allumage", "family": "stop",
        "summary": "La chaudière laisse refroidir le foyer, ventile pour le nettoyer, puis repart en vérification "
                   "pour un nouvel allumage.",
        "substeps": [
            {"name": "Arrêt", "fans": ["{UC10}", "{US10}", "{UA10}"], "auger1": OFF, "auger2": OFF, "plug": OFF},
            {"name": "Nettoyage final", "duration": "{T16}", "fans": ["{UC11}", "{US11}", "{UA11}"],
             "auger1": OFF, "auger2": OFF, "plug": OFF},
        ],
        "transitions": [
            {"when": "", "condition": "fumées > {TH01}", "target": "relight", "sub": "reste en Arrêt"},
            {"when": "", "condition": "fumées < {TH01}", "target": "relight", "sub": "Nettoyage final"},
            {"when": "avant la fin de {T16}", "condition": "fumées > {TH01}", "target": "relight", "sub": "Arrêt"},
            {"when": "fin de {T16}", "condition": "fumées < {TH01}", "target": "check"},
        ],
        "notes": ["La façon d'entrer dans cette étape n'est pas précisée dans le document (bas de la page 16)."],
    },
    {
        "id": "normal", "name": "Normal", "family": "run",
        "summary": "Fonctionnement courant : ventilateurs et vis travaillent au palier de puissance en cours (P1 à P5). "
                   "Avec A05 = 1, le palier suit la température de l'eau.",
        "entry": "Avec {A05} = 1 (puissance proportionnelle), le palier suit la température de l'eau sur une plage {D08}.",
        "substeps": [dict(POWER_ORGANS, name="Régime (palier P1 à P5 en cours)")],
        "transitions": [
            {"when": "combustion à la puissance finale",
             "condition": "fumées < {TH03} ou fumées < thermostat d'extinction de la puissance en cours "
                          "({TH35} {TH36} {TH37} {TH38} {TH39})",
             "target": "pre_extinction"},
            {"when": "", "condition": "fumées > {TH07} ou chaudière > {TH24}", "target": "modulation"},
            *_thermostat_cases("modulation", a07=4, a52=4),
            *STANDBY_ENTRIES,
            *SAFETY_EXITS,
        ],
    },
    {
        "id": "pre_extinction", "name": "Pré-extinction", "family": "stop",
        "summary": "Les fumées sont devenues trop froides : la chaudière continue un moment au même palier. "
                   "Si la situation ne se rétablit pas à temps, elle s'arrête en erreur.",
        "substeps": [dict(POWER_ORGANS, name="Pré-extinction (« Arrêt d'avant »)", duration="{T14}")],
        "transitions": [
            {"when": "avant la fin de {T14}", "condition": "la condition de fin de combustion disparaît",
             "target": "normal"},
            {"when": "fin de {T14}", "condition": "", "target": "shutdown", "error": "Er03"},
        ],
    },
    {
        "id": "modulation", "name": "Modulation", "family": "run",
        "summary": "La température voulue est atteinte : la chaudière ralentit au réglage le plus bas (celui de P1) "
                   "et repasse en Normal quand la demande revient.",
        "substeps": [
            {"name": "Modulation", "fans": ["{UC03}", "{US03}", "{UA03}"], "auger1": "{C03}", "auger2": "{C23}",
             "plug": OFF},
            {"name": "Attente", "duration": "{T55}", "req": {"A13": [1]}, "fans": ["{UC03}", "{US03}", "{UA03}"],
             "auger1": "{C03}", "auger2": "{C23}", "plug": OFF},
        ],
        "transitions": [
            {"when": "", "condition": "fumées < {TH07} et chaudière < {TH24}", "target": "normal"},
            *_thermostat_cases("normal", a07=4, a52=4, closed=True),
            *STANDBY_ENTRIES,
            {"when": "", "condition": "chaudière > {TH24+D10}", "target": "modulation", "sub": "Attente",
             "req": {"A13": [1]}},
            {"when": "Attente, avant la fin de {T55}", "condition": "chaudière < {TH24+D10}", "target": "modulation",
             "req": {"A13": [1]}},
            {"when": "Attente, fin de {T55}", "condition": "chaudière > {TH24+D10}", "target": "standby",
             "note": "après {T22}", "req": {"A13": [1]}},
            *SAFETY_EXITS,
        ],
    },
    {
        "id": "safety", "name": "Sécurité", "family": "danger",
        "summary": "Une température est trop élevée : tout est coupé. Si elle redescend à temps, la chaudière reprend "
                   "là où elle était ; sinon elle s'arrête en erreur de surchauffe.",
        "substeps": [{"name": "Sécurité", "duration": "{T15}", "fans": [OFF, OFF, OFF], "auger1": OFF,
                      "auger2": OFF, "plug": OFF}],
        "entry": "Déclenchement : fumées > {TH08} ou chaudière > {TH25} ou sonde de sécurité > {TH78} (si {P78} = 1).",
        "transitions": [
            {"when": "avant la fin de {T15}",
             "condition": "fumées < {TH08} et chaudière < {TH25} et sonde de sécurité < {TH78}",
             "target": "previous"},
            {"when": "fin de {T15}", "condition": "", "target": "shutdown", "error": "Er04 ou Er05"},
        ],
    },
    {
        "id": "standby", "name": "Standby", "family": "standby",
        "summary": "Il n'y a plus de demande de chaleur : la chaudière se met en veille, soit en s'éteignant "
                   "(A27 = 1), soit en alternant des périodes d'arrêt et de marche réduite (A27 = 0).",
        "substeps": [
            {"name": "Avec arrêt – Attente", "short": "Attente", "duration": "{T13}", "req": {"A27": [1]},
             "fans": ["{UC10}", "{US10}", "{UA10}"], "auger1": OFF, "auger2": OFF, "plug": OFF},
            {"name": "Avec arrêt – Arrêt", "short": "Arrêt", "req": {"A27": [1]}, "fans": ["{UC10}", "{US10}", "{UA10}"],
             "auger1": OFF, "auger2": OFF, "plug": OFF},
            {"name": "Avec arrêt – Nettoyage final", "short": "Nettoyage final", "duration": "{T16}", "req": {"A27": [1]},
             "fans": ["{UC11}", "{US11}", "{UA11}"], "auger1": OFF, "auger2": OFF, "plug": OFF},
            {"name": "Avec arrêt – OFF", "short": "OFF", "req": {"A27": [1]}, "fans": [OFF, OFF, OFF], "auger1": OFF,
             "auger2": OFF, "plug": OFF},
            {"name": "Sans arrêt – OFF", "short": "OFF", "duration": "{T32}", "req": {"A27": [0]}, "fans": [OFF, OFF, OFF],
             "auger1": OFF, "auger2": OFF, "plug": OFF},
            {"name": "Sans arrêt – ON", "short": "ON", "duration": "{T36}", "req": {"A27": [0]},
             "fans": ["{UC09}", "{US09}", "{UA09}"], "auger1": "{C09}", "auger2": "{C29}", "plug": OFF},
        ],
        "transitions": [
            {"when": "fin de {T13}", "condition": "", "target": "standby", "sub": "Arrêt", "req": {"A27": [1]}},
            {"when": "Arrêt", "condition": "fumées < {TH28}", "target": "standby", "sub": "Nettoyage final",
             "req": {"A27": [1]}},
            {"when": "avant la fin de {T16}", "condition": "fumées > {TH28}", "target": "standby", "sub": "Arrêt",
             "req": {"A27": [1]}},
            {"when": "fin de {T16}", "condition": "fumées < {TH28}", "target": "standby", "sub": "OFF",
             "req": {"A27": [1]}},
            {"when": "fin de {T32}", "condition": "", "target": "standby", "sub": "ON", "req": {"A27": [0]}},
            {"when": "fin de {T36}", "condition": "", "target": "standby", "sub": "OFF", "req": {"A27": [0]}},
            {"when": "", "condition": "la condition qui a amené le Standby disparaît", "target": "previous",
             "note": "après {T11}"},
            *SAFETY_EXITS,
        ],
    },
    {
        "id": "shutdown", "name": "Arrêt", "family": "stop",
        "summary": "Extinction normale : plus de pellets, les ventilateurs refroidissent le foyer puis le nettoient. "
                   "Sans erreur, la chaudière revient à OFF.",
        "substeps": [
            {"name": "Attente (« Bloc-Attente » dans le document)", "short": "Attente",
             "fans": ["{UC10}", "{US10}", "{UA10}"],
             "auger1": OFF, "auger2": "{C30}", "plug": OFF},
            {"name": "Nettoyage final (« Bloc-Nettoyage final » dans le document)", "short": "Nettoyage final",
             "duration": "{T16}",
             "fans": ["{UC11}", "{US11}", "{UA11}"], "auger1": OFF, "auger2": OFF, "plug": OFF},
        ],
        "transitions": [
            {"when": "", "condition": "fumées > {TH01}", "target": "shutdown", "sub": "reste en Attente"},
            {"when": "", "condition": "fumées < {TH01}", "target": "shutdown", "sub": "Nettoyage final"},
            {"when": "avant la fin de {T16}", "condition": "fumées > {TH01}", "target": "shutdown", "sub": "Attente"},
            {"when": "fin de {T16}", "condition": "fumées < {TH01} et pas d'erreur", "target": "off"},
            {"when": "fin de {T16}", "condition": "fumées < {TH01} et erreur présente", "target": "shutdown"},
        ],
    },
    {
        "id": "block", "name": "Bloc", "family": "danger",
        "summary": "La chaudière est bloquée et ne redémarre pas seule. Les ventilateurs tournent tant que les fumées "
                   "sont chaudes. Une intervention sur le clavier est nécessaire.",
        "entry": "Ventilateurs en marche seulement si fumées > {TH01}.",
        "substeps": [{"name": "Bloc", "fans": ["{UC03}", "{US03}", "{UA03}"], "auger1": OFF, "auger2": OFF, "plug": OFF}],
        "transitions": [
            {"when": "", "condition": "appui de 3 secondes sur la touche P1 (et aucune autre condition d'arrêt)",
             "target": "off"},
        ],
    },
]

# Where each transition is drawn on the detailed board: index of the transition -> index of
# the sub-step it leaves from. Transitions not listed apply to the whole stage.
TRANSITION_PLACES = {
    "ignition": {1: 0, 2: 1, 3: 2, 4: 3, 5: 3, 6: 3},
    "relight": {0: 0, 1: 0, 2: 1, 3: 1},
    "modulation": {11: 0, 12: 1, 13: 1},
    "standby": {0: 0, 1: 1, 2: 2, 3: 2, 4: 4, 5: 5},
    "shutdown": {0: 0, 1: 0, 2: 1, 3: 1, 4: 1},
}
for _stage in STAGES:
    _places = TRANSITION_PLACES.get(_stage["id"], {})
    _stage["transitions"] = [dict(t, at=_places[i]) if i in _places else t for i, t in enumerate(_stage["transitions"])]


def _per_power(prefix: str) -> list[str]:
    """Markup of the five power steps of a family: UC -> {UC03}..{UC07}, C2 -> {C23}..{C27}."""
    codes = [f"C2{n}" for n in range(3, 8)] if prefix == "C2" else [f"{prefix}0{n}" for n in range(3, 8)]
    return [f"{{{code}}}" for code in codes]


# Everything that depends on the power step P1..P5, side by side (shown in the Normal stage).
POWER_MATRIX = [
    {"group": "Organes", "label": "V1", "cells": _per_power("UC")},
    {"group": "Organes", "label": "V2", "cells": _per_power("US")},
    {"group": "Organes", "label": "V3 extraction", "cells": _per_power("UA")},
    {"group": "Organes", "label": "Vis 1", "cells": _per_power("C")},
    {"group": "Organes", "label": "Vis 2", "cells": _per_power("C2")},
    {"group": "Organes", "label": "Vitesse vis", "cells": _per_power("SC"), "req": {"P21": [1, 2]}},
    {"group": "Dépression", "label": "Consigne", "cells": [f"{{PR0{n}}}" for n in range(2, 7)], "req": {"A30": [1]}},
    {"group": "Dépression", "label": "± écart", "cells": [f"{{PR2{n}}}" for n in range(2, 7)], "req": {"A30": [1]}},
    {"group": "Dépression", "label": "V3 min", "cells": [f"{{UA4{n}}}" for n in range(3, 8)], "req": {"A30": [1]}},
    {"group": "Dépression", "label": "V3 max", "cells": [f"{{UA6{n}}}" for n in range(3, 8)], "req": {"A30": [1]}},
    {"group": "Sonde lambda", "label": "O₂ visé", "cells": [f"{{o0{n}}}" for n in range(3, 8)]},
    {"group": "Sonde lambda", "label": "± plage", "cells": [f"{{o2{n}}}" for n in range(3, 8)]},
    {"group": "Sonde lambda", "label": "V1 min", "cells": [f"{{UC4{n}}}" for n in range(3, 8)]},
    {"group": "Sonde lambda", "label": "V1 max", "cells": [f"{{UC6{n}}}" for n in range(3, 8)]},
    {"group": "Sonde lambda", "label": "V2 min", "cells": [f"{{US4{n}}}" for n in range(3, 8)]},
    {"group": "Sonde lambda", "label": "V2 max", "cells": [f"{{US6{n}}}" for n in range(3, 8)]},
    {"group": "Sonde lambda", "label": "Vis min", "cells": [f"{{C4{n}}}" for n in range(3, 8)]},
    {"group": "Sonde lambda", "label": "Vis max", "cells": [f"{{C6{n}}}" for n in range(3, 8)]},
    {"group": "Sonde lambda", "label": "Vitesse vis min", "cells": [f"{{SC4{n}}}" for n in range(3, 8)], "req": {"P21": [1, 2]}},
    {"group": "Sonde lambda", "label": "Vitesse vis max", "cells": [f"{{SC6{n}}}" for n in range(3, 8)], "req": {"P21": [1, 2]}},
    {"group": "Fin de combustion", "label": "Fumées <", "cells": [f"{{TH3{n}}}" for n in range(5, 10)]},
]
_normal = next(stage for stage in STAGES if stage["id"] == "normal")
_normal["matrix"] = POWER_MATRIX
# Settings of a whole stage that are not an organ value: vacuum set point of the start-up
# phases and auger speed on the variator (the power steps are in the matrix).
_VARIATOR = {"P21": [1, 2]}
_ALSO = {
    "ignition": [{"label": "Dépression", "value": "{PR00} ± {PR20}", "req": {"A30": [1]}},
                 {"label": "Vitesse vis", "value": "{SC01} · 2e allumage {SC08}", "req": _VARIATOR}],
    "stabilisation": [{"label": "Dépression", "value": "{PR01} ± {PR21}", "req": {"A30": [1]}},
                      {"label": "Vitesse vis", "value": "{SC02}", "req": _VARIATOR}],
    "standby": [{"label": "Vitesse vis (sans arrêt, ON)", "value": "{SC09}", "req": _VARIATOR}],
}
for _stage in STAGES:
    if _stage["id"] in _ALSO:
        _stage["also"] = _ALSO[_stage["id"]]

# Functions working alongside the stages. `flow`: the loop, step by step (markup);
# `rows`: (label, markup) settings; `acts_on`: stages where it works; `basis`: where the
# description comes from when it is not the manual's cycle pages.
SYSTEMS = [
    {
        "id": "lambda", "name": "Sonde lambda (O₂)", "acts_on": ["normal", "modulation"],
        "basis": "d'après les libellés des paramètres et les erreurs EL",
        "flow": ["O₂ mesuré {~oxygen}", "comparé à l'O₂ visé du palier ± plage (matrice)",
                 "toutes les {T62}, 1re fois après {T64}",
                 "corrige V1 par pas de {UC81}, V2 par {US81}, vis par {C81}, entre min et max du palier",
                 "hors plage plus de {T63} → Er22 (déduit)"],
        "rows": [["Activation", "régulateur {P58} · module RS485 {P66} → Er16 · erreurs {P60}"],
                 ["Sens de régulation", "V1 {P67} · V2 {P68} · vis {P69} · sorties {P70}"],
                 ["Thermostat lambda", "{TH50} (min {TH51}, max {TH52})"]],
        "errors": ["Er16", "Er22", "EL00…EL08"],
    },
    {
        "id": "vacuum", "name": "Régulateur de dépression", "acts_on": ["ignition", "stabilisation", "normal"],
        "basis": "d'après les libellés des paramètres", "req": {"A30": [1]},
        "flow": ["dépression mesurée", "comparée à la consigne de la phase ± écart",
                 "toutes les {T69}, 1re fois après {T70}", "corrige V3 (extraction) par pas de {UA84}, entre min et max"],
        "rows": [["Activation", "{A30}"],
                 ["Allumage", "{PR00} ± {PR20} · V3 {UA41} … {UA61}"],
                 ["Stabilisation", "{PR01} ± {PR21} · V3 {UA42} … {UA62}"],
                 ["Paliers P1–P5", "matrice de l'étape Normal"],
                 ["Alarmes", "< {PR70} → Er34 · > {PR90} → Er35 · après {T80}"]],
        "errors": ["Er34", "Er35"],
    },
    {
        "id": "power", "name": "Choix du palier P1–P5", "acts_on": ["normal", "modulation"],
        "basis": "d'après les libellés des paramètres",
        "flow": ["température de l'eau", "comparée à la consigne {TH24}", "palier réparti sur {D08} (si {A05} = 1)",
                 "changement après {T17} ({T18} depuis l'allumage, si {A16} = 1)"],
        "rows": [["Paliers", "{P03} puissances"],
                 ["Vis", "période vis 1 {P05} · vis 2 {P13} · mode {P21} · vis 2 {P43} · frein {A28}"],
                 ["Vitesses min.", "V1 {P14} · V2 {P26} · V3 {P27}"],
                 ["Étalonnage", "pas vis {P15} · pas V1 {P16}"]],
    },
    {
        "id": "pellets", "name": "Pellets", "acts_on": ["normal"],
        "basis": "d'après les libellés des paramètres",
        "rows": [["Capteur de niveau", "{P09} · présence après {T25} · manque après {T26} → Er18"],
                 ["Remplissage", "{T23} au-dessus du min. · {T24} jusqu'au min."],
                 ["Thermostat pellet", "alarme après {T38} → Er06"],
                 ["Puissance thermostat pellet", "V1 {UC82} · V2 {US82} · V3 {UA82} · vis {C82} · vitesse {SC82}"]],
        "errors": ["Er06", "Er18"],
    },
    {
        "id": "cleaning", "name": "Nettoyage", "acts_on": ["check", "normal", "shutdown", "relight", "standby"],
        "basis": "d'après les libellés des paramètres",
        "rows": [["Périodique", "toutes les {T07} pendant {T08}"],
                 ["Moteur 1", "arrêt {T27} / marche {T28} · ventilateurs {PA21}"],
                 ["Moteur 2", "{P80} · arrêt {T52} / marche {T53} · fin d'extinction / vérification {T54} · "
                              "ventilateurs {PA22} · activation {TH80} ± {IH80}"],
                 ["Message de nettoyage", "{T71}"]],
    },
    {
        "id": "water", "name": "Eau et thermostats", "acts_on": ["normal", "modulation", "standby", "safety", "off"],
        "basis": "d'après les libellés des paramètres",
        "rows": [["Chaudière", "consigne {TH24} ± {IH24} · plage {TH26} … {TH27} · sécurité {TH25}"],
                 ["Ballon tampon", "{TH29} ± {IH29} · plage {TH55} … {TH56}"],
                 ["Thermostat d'ambiance", "{A07} · à distance {A52} · hydraulique {P35} · chaudière à air {P42}"],
                 ["Sanitaire", "{TH20} … {TH21} · Δ {IH21} · sortie du standby {A29} · fonction {A60} · délai {T68}"],
                 ["Pression d'eau", "{S01} … {S08} · gestion {A14} · type {A20} → Er09 / Er10"],
                 ["Autres thermostats", "échangeur {TH19} ± {IH19} · antigel {TH18} · différentiel {TH30} ± {IH30} · "
                                        "sortie aux. {TH31} ± {IH31}"],
                 ["Installation", "sonde chaudière {PA39} · vanne de sécurité {T50}"]],
        "errors": ["Er09", "Er10"],
    },
    {
        "id": "safety_devices", "name": "Sécurités", "acts_on": ["safety", "normal", "modulation", "standby"],
        "basis": "d'après les libellés des paramètres",
        "rows": [["Haute tension", "HV1 {T09} → Er01 · HV2 pressostat {T10} → Er14 · HV3 {T93}"],
                 ["Sonde de sécurité", "{P78} · {TH78} ± {IH78}"],
                 ["Sécurité moteurs", "{PA41} · {PA42} · {PA43}"],
                 ["Porte ouverte", "V1 {A17} · V2 {A18} · V3 {A19}"]],
        "errors": ["Er01", "Er14"],
    },
    {
        "id": "config", "name": "Configuration", "acts_on": [],
        "basis": "d'après les libellés des paramètres",
        "rows": [["Sorties", "OUT1 {P61} · OUT2 {P62} · OUT3 {P63} · OUT4 {P64} · DAC0 {P101} · DAC1 {P102}"],
                 ["Extinction", "automatique {A40} après {T84} · depuis l'extinction {A10}"],
                 ["Standby", "entrée après {T22} · sortie après {T11} · sortie {A26}"],
                 ["Divers", "recette {P04} · {I10}"]],
    },
]
SYSTEM_IDS = {system["id"] for system in SYSTEMS}

# Detailed board: rows of stage cards. Between two neighbours the page draws →, ← or ⇄
# from the transitions that link them (nothing when none does).
BOARD = [
    {"title": "Démarrage", "items": ["check", "ignition", "stabilisation"]},
    {"title": "Régime et veille", "items": ["normal", "modulation", "standby"]},
    {"title": "Arrêts et danger", "items": ["pre_extinction", "shutdown", "off", "relight", "safety", "block"]},
]

STAGE_IDS = {stage["id"] for stage in STAGES}
SPECIAL_TARGETS = {"previous"}  # "retour à l'état précédent"

# --- diagram ---------------------------------------------------------------------------
# Each stage is a box (top-left x, y and width; the height follows from its content).
# A stage with several sub-steps shows them as small boxes inside, in one or more columns,
# linked by arrows (`loop`: the sub-steps alternate, arrows both ways). A stage with one
# sub-step shows only a subtitle (markup, rendered as plain text with the current value).
VIEWBOX = (1160, 610)
HEADER, SUB_H, SUB_GAP, PAD, GROUP_TITLE, SIMPLE_H = 30, 40, 12, 8, 18, 56

NODE_SPECS = {
    "off": {"x": 20, "y": 20, "w": 140},
    "check": {"x": 190, "y": 20, "w": 150},
    "ignition": {"x": 370, "y": 20, "w": 190, "columns": [{"subs": [0, 1, 2, 3]}]},
    "stabilisation": {"x": 590, "y": 20, "w": 160},
    "normal": {"x": 780, "y": 20, "w": 170, "subtitle": "palier P1 à P5"},
    "pre_extinction": {"x": 980, "y": 20, "w": 150},
    "block": {"x": 20, "y": 160, "w": 140},
    "modulation": {"x": 780, "y": 130, "w": 170, "columns": [{"subs": [0, 1], "loop": True}]},
    "safety": {"x": 980, "y": 160, "w": 150},
    "relight": {"x": 190, "y": 300, "w": 150, "columns": [{"subs": [0, 1]}]},
    "shutdown": {"x": 370, "y": 300, "w": 190, "columns": [{"subs": [0, 1]}]},
    "standby": {"x": 590, "y": 300, "w": 360, "columns": [
        {"subs": [0, 1, 2, 3], "title": "Avec arrêt (A27 = 1)"},
        {"subs": [4, 5], "title": "Sans arrêt (A27 = 0)", "loop": True},
    ]},
}

# Main arrows between stages, as polylines from the border of one box to the border of
# another. An arrow is dashed when no transition from -> to applies with the current
# settings (computed by the page); `from: None` = entry not described by the manual.
# `label_at` = (x, y, text-anchor) of the label; else it sits on the longest segment.
EDGES = [
    {"from": "off", "to": "check", "label": "démarrage", "label_at": (175, 12, "middle"),
     "points": [(160, 48), (190, 48)]},
    {"from": "check", "to": "ignition", "points": [(340, 48), (370, 48)]},
    {"from": "ignition", "to": "stabilisation", "points": [(560, 48), (590, 48)]},
    {"from": "stabilisation", "to": "normal", "points": [(750, 48), (780, 48)]},
    {"from": "normal", "to": "pre_extinction", "points": [(950, 48), (980, 48)]},
    {"from": "normal", "to": "modulation", "points": [(845, 76), (845, 130)]},
    {"from": "modulation", "to": "normal", "points": [(885, 130), (885, 76)]},
    {"from": "normal", "to": "standby", "label": "Standby", "label_at": (758, 190, "end"),
     "points": [(800, 76), (800, 108), (765, 108), (765, 300)]},
    {"from": "modulation", "to": "standby", "label_at": (871, 285, "start"), "points": [(865, 260), (865, 300)]},
    {"from": "normal", "to": "safety", "points": [(950, 66), (965, 66), (965, 175), (980, 175)]},
    {"from": "modulation", "to": "safety", "points": [(950, 200), (980, 200)]},
    {"from": "pre_extinction", "to": "shutdown", "label": "Er03", "label_at": (1000, 600, "middle"),
     "points": [(1130, 48), (1145, 48), (1145, 585), (450, 585), (450, 430)]},
    {"from": "safety", "to": "shutdown", "label": "Er04 / Er05", "label_at": (1061, 400, "start"),
     "points": [(1055, 216), (1055, 570), (480, 570), (480, 430)]},
    {"from": "ignition", "to": "shutdown", "label": "Er12", "label_at": (471, 281, "start"),
     "points": [(465, 254), (465, 300)]},
    {"from": "shutdown", "to": "off", "points": [(400, 430), (400, 555), (175, 555), (175, 100), (130, 100), (130, 76)]},
    {"from": "off", "to": "block", "label": "eau > TH25", "label_at": (66, 125, "start"), "points": [(60, 76), (60, 160)]},
    {"from": "relight", "to": "check", "points": [(265, 300), (265, 76)]},
    {"from": None, "to": "relight", "label": "?", "label_at": (221, 462, "start"), "points": [(215, 470), (215, 430)]},
]


def diagram_layout() -> dict:
    """Boxes of every stage and sub-step, with their computed heights, plus the arrows."""
    stages = {stage["id"]: stage for stage in STAGES}
    nodes = {}
    for stage_id, spec in NODE_SPECS.items():
        stage = stages[stage_id]
        x, y, w = spec["x"], spec["y"], spec["w"]
        columns = spec.get("columns", [])
        node = {"x": x, "y": y, "w": w, "h": SIMPLE_H, "subs": [], "columns": []}
        if not columns:
            node["subtitle"] = spec.get("subtitle", stage["substeps"][0].get("duration", ""))
            nodes[stage_id] = node
            continue
        has_titles = any("title" in column for column in columns)
        top = y + HEADER + (GROUP_TITLE if has_titles else 0)
        col_w = (w - PAD * (len(columns) + 1)) / len(columns)
        rows = max(len(column["subs"]) for column in columns)
        for col, column in enumerate(columns):
            cx = x + PAD + col * (col_w + PAD)
            node["columns"].append({"x": cx, "w": col_w, "title": column.get("title", ""), "loop": column.get("loop", False),
                                    "subs": column["subs"]})
            for row, index in enumerate(column["subs"]):
                sub = stage["substeps"][index]
                node["subs"].append({
                    "index": index, "x": cx, "y": top + row * (SUB_H + SUB_GAP), "w": col_w, "h": SUB_H,
                    "label": sub.get("short", sub["name"]), "duration": sub.get("duration", ""), "req": sub.get("req"),
                })
        node["h"] = top - y + rows * SUB_H + (rows - 1) * SUB_GAP + PAD
        nodes[stage_id] = node
    return {"viewbox": VIEWBOX, "header": HEADER, "nodes": nodes, "edges": EDGES}


DIAGRAM = diagram_layout()

SUMMARY = [
    "Démarrage : vérification, puis allumage en quatre sous-étapes, puis stabilisation du feu.",
    "Régime : Normal au palier P1 à P5, Modulation au réglage le plus bas quand la température est atteinte.",
    "Veille : Standby quand il n'y a plus de demande, avec ou sans extinction selon A27.",
    "Arrêt et danger : pré-extinction si les fumées refroidissent, Sécurité en cas de surchauffe, Arrêt puis OFF, "
    "Bloc si une intervention est nécessaire.",
]

CODE_FAMILIES = [
    ("T…", "Durées (secondes, parfois minutes ou heures)."),
    ("TH…", "Seuils de température (°C). IH… : hystérésis. D… : écarts de température (°C)."),
    ("UC… / US… / UA…", "Ventilateur 1 / ventilateur 2 / ventilateur 3 = extraction (déduit : UA84, A30 et UA41 à UA67 "
                         "concernent le régulateur de dépression du ventilateur d'extraction). Valeurs en %."),
    ("C01 à C09 / C21 à C30", "Vis 1 / vis 2. Valeur en secondes : temps de marche de la vis par période "
                               "(P05 = période de la vis 1, P13 = période de la vis 2, mode pause-travail P21 = 0) (déduit)."),
    ("Suffixes", "01 = allumage, 02 = stabilisation, 03 à 07 = puissances P1 à P5, 08 = 2e allumage, 09 = standby, "
                 "10 = extinction, 11 = nettoyage (vis 2 : 21 à 30 dans le même ordre)."),
    ("A…", "Habilitations : interrupteurs 0 / 1 / 2…"),
    ("P… / PA…", "Configuration de base."),
    ("PR…", "Régulateur de dépression."),
    ("S…", "Capteur de pression d'eau."),
    ("SC…", "Vitesse de la vis au variateur (sans effet si P21 = 0)."),
    ("o…", "Niveaux et plages d'oxygène (régulateur lambda)."),
    ("TH35 à TH39", "Thermostat d'extinction par puissance P1 à P5."),
    ("Puissance utilisateur", "Dans le document : le palier P1 à P5 en cours. Les tableaux affichent les cinq valeurs."),
]

ERRORS = [
    {"code": "Er01", "label": "Thermostat de sécurité HV activé", "stages": [], "params": ["T09"]},
    {"code": "Er03", "label": "Arrêt accidentel : températures des fumées trop basses", "stages": ["pre_extinction"],
     "params": ["T14", "TH03"]},
    {"code": "Er04", "label": "Surchauffe chaudière", "stages": ["safety"], "params": ["TH25", "T15"]},
    {"code": "Er05", "label": "Surchauffe des fumées", "stages": ["safety"], "params": ["TH08", "T15"]},
    {"code": "Er06", "label": "Thermostat pellet", "stages": [], "params": ["T38"]},
    {"code": "Er07*", "label": "Encodeur : signal absent", "stages": [], "params": []},
    {"code": "Er08*", "label": "Encodeur : problème d'adaptation du nombre de tours", "stages": [], "params": []},
    {"code": "Er09", "label": "Pression d'eau faible", "stages": [], "params": ["S01", "A14"], "flag": "A14"},
    {"code": "Er10", "label": "Pression d'eau élevée", "stages": [], "params": ["S08", "A14"], "flag": "A14"},
    {"code": "Er11", "label": "Horloge temps réel", "stages": [], "params": []},
    {"code": "Er12", "label": "Allumage échoué", "stages": ["ignition", "stabilisation"], "params": ["P02", "TH06"]},
    {"code": "Er14", "label": "Pressostat", "stages": [], "params": ["T10"]},
    {"code": "Er15", "label": "Manque de tension", "stages": [], "params": []},
    {"code": "Er16", "label": "Communication avec le module lambda", "stages": [], "params": ["P66"]},
    {"code": "Er18", "label": "Arrêt par manque de pellets", "stages": [], "params": ["T25", "T26", "P09"]},
    {"code": "Er22", "label": "Régulateur lambda", "stages": [], "params": ["P58", "P60"]},
    {"code": "Er34", "label": "Dépression sous le seuil minimum", "stages": [], "params": ["PR70", "T80"]},
    {"code": "Er35", "label": "Dépression au-dessus du seuil maximal (le document écrit « au-dessous », coquille probable)",
     "stages": [], "params": ["PR90", "T80"]},
]
ERRORS_NOTE = "* Seulement pour les produits avec encodeur. Paramètres liés : d'après leurs libellés."

_SENSOR_FIX = "Désactiver la carte, vérifier les connexions de la sonde lambda, remplacer le capteur."
_POWER_FIX = ("Débrancher le module lambda du 230 Vac, vérifier tous les fusibles de la carte, vérifier que la tension "
              "de ligne est de 230 Vac ± 20 %.")
LAMBDA_ERRORS = [
    {"code": "EL00", "label": "Erreur générique", "fix": "« Désactiver et sur la carte » (texte incomplet dans le document)"},
    {"code": "EL01", "label": "Capteur de chauffage en court-circuit à la masse", "fix": _SENSOR_FIX},
    {"code": "EL02", "label": "Capteur de chauffage ouvert", "fix": _SENSOR_FIX},
    {"code": "EL03", "label": "Capteur de chauffage en court-circuit à 12 V", "fix": _SENSOR_FIX},
    {"code": "EL04", "label": "Capteur lambda en court-circuit à la masse", "fix": _SENSOR_FIX},
    {"code": "EL05", "label": "Tension d'alimentation de chauffage basse", "fix": _POWER_FIX},
    {"code": "EL06", "label": "Tension d'alimentation de la sonde lambda trop faible", "fix": _POWER_FIX},
    {"code": "EL07", "label": "Défaillance du capteur de chauffage",
     "fix": "Vérifier que le capteur chauffe, activer sur la carte et vérifier une nouvelle procédure de réchauffement."},
    {"code": "EL08", "label": "Sonde lambda en surtempérature",
     "fix": "Le capteur ne doit pas être exposé à des flammes ou à des fumées au-dessus de 700 °C. Déplacer le capteur "
            "ou abaisser la température."},
]
LAMBDA_WARNING = "Désactiver le module avant de débrancher la sonde lambda"

SHADOWS = [
    "P42 = 1 dans les réglages actuels (chaudière à air) alors que toutes les conditions de passage vers Modulation et "
    "Standby par thermostat sont écrites pour P42 = 0 (hydro). Pour P42 = 1, le document ne dit pas ce qui se passe. "
    "Seule la transition Normal → Modulation par température (fumées > TH07 ou chaudière > TH24) n'a pas cette condition.",
    "L'entrée dans « Reprise d'allumage » n'est pas précisée (bas de la page 16).",
    "Au 1er allumage variable, le libellé des ventilateurs est « I Allumage » mais les valeurs citées sont celles du "
    "2e allumage (UC08 / US08 / UA08) ; on suppose UC01 / US01 / UA01 pour le 1er.",
    "Stabilisation : le seuil de la bougie est coupé dans le document (« TH0… »), supposé TH02.",
    "Stabilisation : le cas « T06 écoulé avec des fumées entre TH06 et TH06 + D01 » n'est pas décrit.",
    "Page 16 : deux lignes de la sous-étape Arrêt portent la même condition « fumées > TH01 » mais mènent à des états "
    "différents ; la seconde est lue comme « < TH01 ».",
    "Modulation / Attente : le document écrit T54 (dans l'export : temps du moteur de nettoyage 2) ; lu comme T55.",
    "Pages 17-18 : la cellule « modulation » est continue d'une page à l'autre ; la condition « fumées > TH07 ou "
    "chaudière > TH24 » est rattachée à Normal → Modulation d'après cette lecture.",
    "Pages 18 et 20 : la ligne « fumées > TH08 » est placée juste sous le groupe Standby et sa cellule « prochain état » "
    "est ambiguë ; elle est rattachée à Sécurité, comme le confirme la page 21.",
    "Pages 22-23 : les sous-étapes de l'Arrêt sont nommées « Bloc-Attente » et « Bloc-Nettoyage final » ; à la fin de "
    "T16 avec une erreur présente, le document indique « → Arrêt ».",
    "Page 14 : pour la Vérification, la case « vis sans fin 2 » est vide.",
    "Page 13 : note manuscrite en haut de page, « Porte = disj. moteur er(?) », non interprétée.",
    "Le libellé de A27 cite T26 là où le document utilise T36 (Standby sans arrêt).",
    "L'export compte 289 paramètres (et non 288).",
]


# --- references and payload ----------------------------------------------------------

_BRACES = re.compile(r"\{([^}]+)\}")
_POWER = re.compile(r"@P\((\w+)\)")


def expand_power(prefix: str) -> list[str]:
    """@P(UC) -> UC03..UC07, @P(C2) -> C23..C27."""
    if prefix == "C2":
        return [f"C{number}" for number in range(23, 28)]
    return [f"{prefix}{number:02d}" for number in range(3, 8)]


def codes_in(value) -> list[str]:
    """Every parameter code referenced by a markup text, a list of alternatives or a req."""
    found: list[str] = []
    if isinstance(value, str):
        for group in _BRACES.findall(value):
            if not group.startswith("~"):  # {~oxygen} = latest measurement, not a parameter
                found += [part.strip() for part in group.split("+")]
        for prefix in _POWER.findall(value):
            found += expand_power(prefix)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "req":
                found += list(item)
            elif key not in ("target", "id", "family", "name", "label", "sub"):
                found += codes_in(item)
    elif isinstance(value, list):
        for item in value:
            found += codes_in(item)
    return found


def stage_codes(stage: dict) -> list[str]:
    """Codes of one stage, in order of first appearance."""
    return list(dict.fromkeys(codes_in(stage)))


def stages_by_code() -> dict[str, list[str]]:
    """Reverse index: code -> ids of the stages and parallel functions where it appears."""
    index: dict[str, list[str]] = {}
    for block in STAGES + SYSTEMS:
        for code in stage_codes(block):
            index.setdefault(code, []).append(block["id"])
    return index


def build_payload(parameter_rows: list[dict], live: dict | None = None) -> dict:
    """Everything the page needs, as plain JSON: the cycle plus every parameter with its values.

    `parameter_rows` are the rows built by the parameter list page (code, section, description,
    unit, baseline, current, modified, change_count, last_change). `live` = latest readings
    of the logger ({"oxygen": 14.2, "time": "..."}), shown in the parallel functions.
    Parameters stored in the app but placed nowhere in the board are listed in `unplaced`.
    """
    index = stages_by_code()
    parameters = {}
    for row in parameter_rows:
        code = row["code"]
        parameters[code] = {
            "code": code,
            "label": label_for(code),
            "description": row["description"],
            "section": row["section"],
            "unit": row["unit"],
            "baseline": row["baseline"],
            "current": row["current"],
            "modified": row["modified"],
            "change_count": row["change_count"],
            "last_change": row["last_change"].strftime("%d.%m.%Y %H:%M") if row["last_change"] else "",
            "impact": impact_for(code),
            "constraint": CONSTRAINTS.get(code),
            "stages": index.get(code, []),
            "missing": False,
        }
    for code, info in MISSING_PARAMETERS.items():
        if code not in parameters:
            parameters[code] = {
                "code": code, "label": info["label"], "description": info["description"], "section": "",
                "unit": info["unit"], "baseline": "", "current": "", "modified": False, "change_count": 0,
                "last_change": "", "impact": impact_for(code), "constraint": CONSTRAINTS.get(code),
                "stages": index.get(code, []), "missing": True,
            }
    stages = [dict(stage, codes=stage_codes(stage)) for stage in STAGES]
    systems = [dict(system, codes=stage_codes(system)) for system in SYSTEMS]
    return {
        "families": FAMILIES,
        "stages": stages,
        "systems": systems,
        "board": BOARD,
        "live": live or {},
        "unplaced": sorted(code for code in parameters if code not in index),
        "diagram": DIAGRAM,
        "summary": SUMMARY,
        "code_families": CODE_FAMILIES,
        "errors": ERRORS,
        "errors_note": ERRORS_NOTE,
        "lambda_errors": LAMBDA_ERRORS,
        "lambda_warning": LAMBDA_WARNING,
        "shadows": SHADOWS,
        "parameters": parameters,
    }
