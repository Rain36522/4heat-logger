import json
import unittest
from datetime import datetime

from monitor.core import boiler_cycle as bc


def all_transitions():
    for stage in bc.STAGES:
        for transition in stage["transitions"]:
            yield stage["id"], transition


def all_reqs():
    for stage in bc.STAGES:
        for item in stage["substeps"] + stage["transitions"]:
            if "req" in item:
                yield stage["id"], item["req"]
            for value in [item.get("auger1"), item.get("auger2"), *item.get("fans", [])]:
                if isinstance(value, list):
                    yield from ((stage["id"], alt["req"]) for alt in value if "req" in alt)


class CycleDataTests(unittest.TestCase):
    def test_every_transition_target_exists(self):
        for stage_id, transition in all_transitions():
            self.assertIn(transition["target"], bc.STAGE_IDS | bc.SPECIAL_TARGETS, f"{stage_id}: {transition}")

    def test_every_referenced_code_is_a_known_parameter(self):
        known = set(bc.EXPORT_CODES) | set(bc.MISSING_PARAMETERS)
        for stage in bc.STAGES:
            unknown = set(bc.stage_codes(stage)) - known
            self.assertFalse(unknown, f"{stage['id']}: {unknown}")
        for error in bc.ERRORS:
            self.assertLessEqual(set(error["params"]), known, error["code"])
            self.assertLessEqual(set(error["stages"]), bc.STAGE_IDS, error["code"])

    def test_only_th24_and_th29_are_missing_from_the_export(self):
        self.assertEqual(set(bc.MISSING_PARAMETERS), {"TH24", "TH29"})
        self.assertFalse(set(bc.MISSING_PARAMETERS) & set(bc.EXPORT_CODES))
        self.assertEqual(len(bc.EXPORT_CODES), 289)
        self.assertEqual(len(set(bc.EXPORT_CODES)), 289)

    def test_every_settings_condition_is_valid(self):
        reqs = list(all_reqs())
        self.assertTrue(reqs)
        for stage_id, req in reqs:
            self.assertTrue(req, stage_id)
            for code, allowed in req.items():
                self.assertIn(code, bc.EXPORT_CODES, f"{stage_id}: {code}")
                self.assertTrue(allowed and all(isinstance(value, int) for value in allowed), f"{stage_id}: {code}")

    def test_the_diagram_draws_every_stage_and_only_real_transitions(self):
        self.assertEqual(set(bc.DIAGRAM["nodes"]), bc.STAGE_IDS)
        for edge in bc.DIAGRAM["edges"]:
            self.assertIn(edge["to"], bc.STAGE_IDS)
            self.assertTrue(edge["from"] is None or edge["from"] in bc.STAGE_IDS)
            self.assertGreaterEqual(len(edge["points"]), 2)

    def test_arrows_start_and_end_on_the_border_of_their_boxes(self):
        nodes = bc.DIAGRAM["nodes"]

        def on_border(point, box):
            x, y = point
            inside_x = box["x"] - 0.5 <= x <= box["x"] + box["w"] + 0.5
            inside_y = box["y"] - 0.5 <= y <= box["y"] + box["h"] + 0.5
            on_side = min(abs(x - box["x"]), abs(x - box["x"] - box["w"]), abs(y - box["y"]), abs(y - box["y"] - box["h"])) < 0.5
            return inside_x and inside_y and on_side

        for edge in bc.DIAGRAM["edges"]:
            if edge["from"]:
                self.assertTrue(on_border(edge["points"][0], nodes[edge["from"]]), edge)
            self.assertTrue(on_border(edge["points"][-1], nodes[edge["to"]]), edge)

    def test_boxes_do_not_overlap_and_fit_in_the_drawing(self):
        width, height = bc.VIEWBOX
        boxes = list(bc.DIAGRAM["nodes"].items())
        for name, box in boxes:
            self.assertLessEqual(box["x"] + box["w"], width, name)
            self.assertLessEqual(box["y"] + box["h"], height, name)
            for sub in box["subs"]:  # sub-steps inside their stage box
                self.assertTrue(box["x"] <= sub["x"] and sub["x"] + sub["w"] <= box["x"] + box["w"], name)
                self.assertTrue(box["y"] <= sub["y"] and sub["y"] + sub["h"] <= box["y"] + box["h"], name)
        for i, (name_a, a) in enumerate(boxes):
            for name_b, b in boxes[i + 1:]:
                apart = a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]
                self.assertTrue(apart, f"{name_a} / {name_b}")

    def test_arrows_are_straight_lines_that_do_not_cross_other_boxes(self):
        def crosses(p, q, box, margin=1):
            (x1, y1), (x2, y2) = p, q
            if x1 == x2:
                return (box["x"] + margin < x1 < box["x"] + box["w"] - margin
                        and max(min(y1, y2), box["y"] + margin) < min(max(y1, y2), box["y"] + box["h"] - margin))
            return (box["y"] + margin < y1 < box["y"] + box["h"] - margin
                    and max(min(x1, x2), box["x"] + margin) < min(max(x1, x2), box["x"] + box["w"] - margin))

        for edge in bc.DIAGRAM["edges"]:
            for p, q in zip(edge["points"], edge["points"][1:]):
                self.assertTrue(p[0] == q[0] or p[1] == q[1], f"{edge}: segments are horizontal or vertical")
                for name, box in bc.DIAGRAM["nodes"].items():
                    self.assertFalse(crosses(p, q, box), f"{edge['from']} -> {edge['to']} crosses {name}")

    def test_every_sub_step_of_a_multi_step_stage_is_drawn(self):
        for stage in bc.STAGES:
            subs = bc.DIAGRAM["nodes"][stage["id"]]["subs"]
            if len(stage["substeps"]) > 1:
                self.assertEqual(sorted(sub["index"] for sub in subs), list(range(len(stage["substeps"]))), stage["id"])

    def test_standby_is_reached_only_through_conditional_transitions(self):
        # The page greys the Standby arrows when none of these applies with the current settings.
        to_standby = [t for stage_id, t in all_transitions() if t["target"] == "standby" and stage_id != "standby"]
        self.assertTrue(to_standby)
        self.assertTrue(all("req" in t for t in to_standby))

    def test_every_exported_parameter_is_placed_in_the_schema(self):
        index = bc.stages_by_code()
        self.assertEqual([code for code in bc.EXPORT_CODES if code not in index], [])

    def test_parallel_functions_and_board_are_consistent(self):
        known = set(bc.EXPORT_CODES) | set(bc.MISSING_PARAMETERS)
        self.assertFalse(bc.SYSTEM_IDS & bc.STAGE_IDS)
        for system in bc.SYSTEMS:
            self.assertLessEqual(set(bc.stage_codes(system)), known, system["id"])
            self.assertLessEqual(set(system["acts_on"]), bc.STAGE_IDS, system["id"])
        on_board = [stage_id for row in bc.BOARD for stage_id in row["items"]]
        self.assertEqual(sorted(on_board), sorted(bc.STAGE_IDS))  # every stage exactly once
        for stage in bc.STAGES:
            for transition in stage["transitions"]:
                if "at" in transition:
                    self.assertLess(transition["at"], len(stage["substeps"]), stage["id"])
        for row in bc.POWER_MATRIX:
            self.assertEqual(len(row["cells"]), 5, row["label"])

    def test_every_exported_parameter_has_a_french_label(self):
        unlabelled = [code for code in bc.EXPORT_CODES if not bc.label_for(code)]
        self.assertEqual(unlabelled, ["I10"])  # no description at all in the export

    def test_labels_built_by_rule(self):
        self.assertEqual(bc.label_for("UC01"), "Ventilateur 1 – allumage")
        self.assertEqual(bc.label_for("C23"), "Vis 2 – puissance P1")
        self.assertEqual(bc.label_for("C30"), "Vis 2 – extinction")
        self.assertEqual(bc.label_for("UA45"), "Ventilateur 3 (extraction) – vitesse min. du régulateur de dépression – puissance P3")
        self.assertEqual(bc.label_for("PR00"), "Consigne du régulateur de dépression – allumage")
        self.assertEqual(bc.label_for("TH37"), "Thermostat d'extinction – puissance P3")
        self.assertEqual(bc.label_for("o25"), "Plage d'oxygène – puissance P3")

    def test_markup_codes(self):
        self.assertEqual(bc.codes_in("fumées > {TH06+D01} et {P02}"), ["TH06", "D01", "P02"])
        self.assertEqual(bc.codes_in("@P(C2)"), ["C23", "C24", "C25", "C26", "C27"])

    def test_reverse_index(self):
        index = bc.stages_by_code()
        self.assertEqual(index["TH09"], ["check", "ignition", "stabilisation"])
        self.assertIn("modulation", index["A13"])


class PayloadTests(unittest.TestCase):
    def test_values_come_from_the_rows_and_missing_codes_are_added(self):
        rows = [{"code": "D08", "section": "Delta", "description": "Delta temperature", "unit": "°C", "baseline": "8",
                 "current": "12", "modified": True, "change_count": 1, "last_change": datetime(2026, 11, 3, 11, 56)}]
        payload = bc.build_payload(rows, {"oxygen": 14.2, "time": "06.11.2026 10:00"})
        json.dumps(payload)
        self.assertEqual(payload["live"]["oxygen"], 14.2)
        self.assertEqual(payload["unplaced"], [])  # D08 is placed (Normal, power function)
        self.assertIn("power", payload["parameters"]["D08"]["stages"])
        d08 = payload["parameters"]["D08"]
        self.assertEqual((d08["current"], d08["last_change"], d08["constraint"]["multiple_of"]), ("12", "03.11.2026 11:56", 4))
        self.assertTrue(payload["parameters"]["TH24"]["missing"])
        self.assertIn("modulation", payload["parameters"]["TH24"]["stages"])
        ignition = next(stage for stage in payload["stages"] if stage["id"] == "ignition")
        self.assertIn("T02", ignition["codes"])
