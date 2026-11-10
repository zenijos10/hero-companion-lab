"""M2 route integration smoke using a real game-data power, without a solve.

Run: python tools/test_build_evaluation_route.py
Uses Flask's in-process client. No user saves are loaded or written.
"""
import copy
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="hc-evaluation-test-")

import server as srv  # noqa: E402
import first_principles as fp  # noqa: E402


class BuildEvaluateRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = srv.app.test_client()
        game_powers = srv.POWERS["Blaster_Ranged.Fire_Blast"]
        attack = next(p for p in game_powers if p.get("is_attack"))
        cls.build = {
            "archetype": "Class_Blaster",
            "primary": "Blaster_Ranged.Fire_Blast",
            "secondary": "Blaster_Support.Fire_Manipulation",
            "powers": [{"full_name": attack["full_name"], "slots": []}],
        }

    def test_default_is_plus_four_with_separate_raw_and_scenario_damage(self):
        before = copy.deepcopy(self.build)
        response = self.client.post("/build/evaluate", json={"build": self.build})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:500])
        data = response.get_json()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["scenario"]["id"], "rating_plus4")
        self.assertEqual(data["scenario"]["enemy_level_shift"], 4)
        self.assertEqual(data["versions"]["model"], fp.MODEL_VERSION)
        self.assertIn("single_target_dps_raw", data["measurements"]["offense"])
        self.assertIn("scenario_personal_dps", data["measurements"]["offense"])
        self.assertEqual(data["ratings"]["status"], "rated")
        self.assertEqual(data["ratings"]["scenario"], "rating_plus4")
        self.assertEqual(self.build, before)

    def test_original_general_solver_preset_is_unchanged(self):
        self.assertEqual(fp.SCENARIOS["general"]["shift"], 1)
        # the rating scenario is NOT a solver content: it must not leak into SCENARIOS
        self.assertNotIn("rating_plus4", fp.SCENARIOS)
        response = self.client.post("/build/evaluate",
                                    json={"build": self.build, "scenario": "general"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["scenario"]["enemy_level_shift"], 1)
        # thresholds are calibrated at +4: a +1 evaluation is not graded against them
        self.assertEqual(response.get_json()["ratings"]["status"], "not_rated")

    def test_unknown_power_is_disclosed_instead_of_hidden(self):
        build = copy.deepcopy(self.build)
        build["powers"].append({"full_name": "Missing.Powerset.Power", "slots": []})
        response = self.client.post("/build/evaluate", json={"build": build})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
        self.assertIn("Missing.Powerset.Power",
                      response.get_json()["unsupported"]["unknown_power_records"])

    def test_invalid_requests_fail_cleanly(self):
        cases = (
            {},
            {"build": {"archetype": "Class_Blaster"}},
            {"build": self.build, "scenario": "unknown"},
            {"build": dict(self.build, exemplar_level=35)},
            {"build": dict(self.build, powers=[None])},
            {"build": dict(self.build, powers=[{"full_name": [], "slots": []}])},
            {"build": dict(self.build, powers=[{"full_name": "X", "slots": "bad"}])},
            {"build": dict(self.build, powers=[{"full_name": "X", "slots": [3]}])},
            {"build": dict(self.build, archetype="NoSuchArchetype")},
            {"build": dict(self.build, pvp=True)},
        )
        for body in cases:
            with self.subTest(body=str(body)[:80]):
                response = self.client.post("/build/evaluate", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["ok"])


    def test_full_level_exemplar_values_evaluate_like_calculate(self):
        for level in (50, 0, ""):
            with self.subTest(level=level):
                response = self.client.post(
                    "/build/evaluate", json={"build": dict(self.build, exemplar_level=level)})
                self.assertEqual(response.status_code, 200)

    def test_suppressible_defense_is_rated_in_combat(self):
        """A real Hide-class power: /build/calculate's in_combat value is what
        /build/evaluate reports as defense."""
        hide = "Stalker_Defense.Super_Reflexes.Hide"
        build = {"archetype": "Class_Stalker", "powers": [{"full_name": hide, "slots": []}]}
        if hide not in srv.POWER_BY_FULL:
            self.skipTest("no Hide record")
        calc = self.client.post("/build/calculate", json=build).get_json()
        fight = {t: r.get("in_combat") for t, r in calc["defense"].items() if "in_combat" in r}
        self.assertTrue(fight, "Hide should carry suppressible defense")
        data = self.client.post("/build/evaluate", json={"build": build}).get_json()
        survival = data["measurements"]["survival"]
        for t, value in fight.items():
            self.assertAlmostEqual(survival["defense"][t]["value"], value, places=2)
            self.assertIn(t, survival["defense_out_of_combat"])


if __name__ == "__main__":
    unittest.main()
