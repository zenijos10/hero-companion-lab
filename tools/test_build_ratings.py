"""M4 battery: S-F ratings (server/build_ratings.py + data/rating_thresholds.json).

Unit half: the grading rules on stub evaluations (cut boundaries, the four
non-letter labels, not_rated on a scenario or fingerprint mismatch).
Real half: the shipped thresholds file is current against the live rating
scenario and model, monotonic, and a real build through /build/evaluate is
rated; an incomplete-offense build gets Unknown offense, never a letter.

Run: python tools/test_build_ratings.py
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-ratings-"))

import build_evaluation  # noqa: E402
import build_ratings as br  # noqa: E402
import first_principles  # noqa: E402

CUTS = {"S": 90.0, "A": 70.0, "B": 50.0, "C": 30.0, "D": 10.0}


def stub_eval(st=60.0, offense_ok=True, pets=0.0, control=0.0, scenario="rating_plus4",
              fingerprint="fp1"):
    m = lambda v: {"value": v}  # noqa: E731
    return {
        "scenario": {"id": scenario},
        "versions": {"scenario_fingerprint": fingerprint},
        "confidence": {"offense_complete": offense_ok},
        "measurements": {
            "offense": {"scenario_single_target_dps": m(st), "scenario_aoe_dps_per_target": m(20.0),
                        "scenario_pet_dps": m(pets)},
            "survival": {"time_to_live": m(None),
                         "defense": {k: m(45.0) for k in ("Melee", "Ranged", "AoE")},
                         "resistance": {}},
            "resources": {"net_per_second": m(0.5), "global_recharge": m(80.0)},
            "support": {"control_proxy": m(control),
                        "team_support": {"summary": {}}},
        },
    }


def stub_thresholds():
    return {"version": 9, "scenario": "rating_plus4", "scenario_fingerprint": "fp1",
            "method": "test", "categories": {k: {"cuts": dict(CUTS)} for k in br.CATEGORIES}}


class GradingRuleTests(unittest.TestCase):
    def rate(self, **kw):
        return br.rate(stub_eval(**kw), stub_thresholds())

    def test_cut_boundaries(self):
        for value, want in ((90.0, "S"), (89.99, "A"), (70.0, "A"), (50.0, "B"),
                            (30.0, "C"), (10.0, "D"), (9.99, "F"), (-5.0, "F")):
            with self.subTest(value=value):
                self.assertEqual(br.grade(value, CUTS), want)

    def test_value_rides_beside_the_grade(self):
        row = self.rate(st=72.0)["categories"]["single_target_damage"]
        self.assertEqual((row["grade"], row["value"], row["cuts"]), ("A", 72.0, CUTS))

    def test_non_letter_labels(self):
        cats = self.rate(offense_ok=False)["categories"]
        self.assertEqual(cats["single_target_damage"]["grade"], "Unknown")   # unread damage
        self.assertEqual(cats["aoe_damage"]["grade"], "Unknown")
        self.assertEqual(cats["pet_damage"]["grade"], "N/A")                # no pets
        self.assertEqual(cats["control"]["grade"], "None")                  # absent capability
        self.assertEqual(cats["survival"]["grade"], "Unknown")              # not measured
        self.assertEqual(cats["resistance"]["grade"], "Unknown")            # incomplete vector
        self.assertEqual(cats["defense"]["grade"], "C")                     # 45 >= the C cut

    def test_pets_and_capabilities_grade_when_present(self):
        cats = self.rate(pets=95.0, control=55.0)["categories"]
        self.assertEqual(cats["pet_damage"]["grade"], "S")
        self.assertEqual(cats["control"]["grade"], "B")

    def test_not_rated_against_the_wrong_fight(self):
        self.assertEqual(br.rate(stub_eval(), None)["status"], "not_rated")
        self.assertEqual(self.rate(scenario="general")["status"], "not_rated")
        stale = self.rate(fingerprint="changed")
        self.assertEqual(stale["status"], "not_rated")
        self.assertIn("recalibrate", stale["reason"])


class ShippedThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.thresholds = br.load_thresholds()
        import server as srv
        cls.srv = srv
        cls.client = srv.app.test_client()

    def test_thresholds_are_current_and_monotonic(self):
        t = self.thresholds
        self.assertIsNotNone(t)
        self.assertEqual(t["scenario"], build_evaluation.DEFAULT_SCENARIO)
        sc = build_evaluation.scenario_params(t["scenario"])
        self.assertEqual(t["scenario_fingerprint"], build_evaluation._fingerprint(sc),
                         "rating scenario changed: run tools/calibrate_rating_thresholds.py")
        self.assertEqual(t["model_version"], first_principles.MODEL_VERSION,
                         "model bumped: recalibrate the rating thresholds")
        self.assertEqual(set(t["categories"]), set(br.CATEGORIES))
        graded = 0
        for key, row in t["categories"].items():
            cuts = row["cuts"]
            if cuts is None:
                continue
            graded += 1
            seq = [cuts[g] for g in br.GRADES]
            self.assertEqual(seq, sorted(seq, reverse=True), key)
        core = ("single_target_damage", "aoe_damage", "survival", "defense", "resistance",
                "endurance", "recharge")
        for key in core:
            self.assertIsNotNone(t["categories"][key]["cuts"], key)
        print(f"{graded} of {len(br.CATEGORIES)} categories carry cut points; "
              f"{t['sample']['contexts']} champion contexts sampled")

    def test_server_loads_the_same_file(self):
        self.assertEqual(self.srv.RATING_THRESHOLDS, self.thresholds)

    def build(self, at, pri, sec):
        ap = self.client.post("/build/autopick", json={
            "archetype": at, "primary": pri, "secondary": sec, "content": "general"}).get_json()
        solved = self.client.post("/build/solve", json={
            "archetype": at, "content": "general", "tier": "premium", "preserve": False,
            "powers": ap["powers"]}).get_json()
        return {"archetype": at, "primary": pri, "secondary": sec, "powers": solved["powers"]}

    def test_a_real_build_is_rated(self):
        data = self.client.post("/build/evaluate", json={"build": self.build(
            "Class_Brute", "Brute_Melee.Super_Strength", "Brute_Defense.Invulnerability")}).get_json()
        ratings = data["ratings"]
        self.assertEqual(ratings["status"], "rated")
        self.assertTrue(ratings["provisional"])
        letters = {r["grade"] for r in ratings["categories"].values()}
        self.assertTrue(letters & set("SABCDF"), letters)
        for row in ratings["categories"].values():
            if row["grade"] in tuple("SABCDF"):
                self.assertIsNotNone(row["value"])

    def test_incomplete_offense_is_never_graded(self):
        build = self.build("Class_Blaster", "Blaster_Ranged.Archery", "Blaster_Support.Tactical_Arrow")
        names = {p["full_name"] for p in build["powers"]}
        if "Blaster_Ranged.Archery.Ranged_Shot" not in names:
            build["powers"].append({"full_name": "Blaster_Ranged.Archery.Ranged_Shot", "slots": [None]})
        cats = self.client.post("/build/evaluate", json={"build": build}).get_json()["ratings"]["categories"]
        self.assertEqual(cats["single_target_damage"]["grade"], "Unknown")
        self.assertEqual(cats["aoe_damage"]["grade"], "Unknown")


if __name__ == "__main__":
    unittest.main()
