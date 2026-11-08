"""M2 evaluation contract tests (no optimizer, certification or real saves).

Run: python tools/test_build_evaluation_contract.py
"""
import copy
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import build_evaluation as ev


class EvaluationContractTests(unittest.TestCase):
    def setUp(self):
        self.build = {"archetype": "Class_Test", "primary": "Test.One",
                      "secondary": "Test.Two",
                      "powers": [{"full_name": "Test.One.Power", "slots": []}]}
        self.ctx = {"power_by_full": {"Test.One.Power": {}}}
        self.scenarios = {
            "rating_plus4": dict(shift=4, enemies=4, teammates=0, length=30.0),
            "general": dict(shift=1, enemies=4, teammates=0, length=30.0),
        }
        self.totals = {
            "defense": {"Melee": {"value": 45.0}},
            "resistance": {"Fire": {"value": 75.0}},
            "recharge": {"value": 50.0},
            "offense": {"st_dps": 100.0, "aoe_dps": 20.0, "aoe_burst": 250.0},
            "endurance": {"recovery_per_sec": 2.0, "chain_drain_per_sec": 1.5,
                          "toggle_drain_per_sec": 0.25, "net_per_sec": 0.25,
                          "sustainable": True},
        }
        self.encounter = dict(my_dps=43.0, amplified=2.0, prevented=15.0,
                              ttl=120.0, availability=0.95, hit_ml=0.05,
                              hit_rn=0.10, hit_out=0.54)

    def evaluate(self, *, build=None, scenario="rating_plus4"):
        with patch.object(ev.first_principles, "SCENARIOS", self.scenarios), \
             patch.object(ev.engine, "calculate_build", return_value=self.totals) as calc, \
             patch.object(ev.first_principles, "encounter_value", return_value=self.encounter) as ep, \
             patch.object(ev.role_output, "build_control_output",
                          return_value=(25.0, [("Hold", 25.0)])), \
             patch.object(ev.role_output, "build_control_uptime",
                          return_value={"controls": []}), \
             patch.object(ev.role_output, "build_heal_output",
                          return_value={"team_hps": 1, "self_hps": 2, "rez": 0}), \
             patch.object(ev.role_output, "enhanced_debuff_totals",
                          return_value={"Regeneration": 50}), \
             patch.object(ev.role_output, "enhanced_team_buffs",
                          return_value={"Defense": 15}):
            result = ev.evaluate(self.build if build is None else build, scenario,
                                 ctx=self.ctx, set_bonuses={}, res_cap=75,
                                 archetype_record={"name": "Class_Test", "hitpoints": 1000},
                                 db_name="Homecoming", db_version="test-123",
                                 app_version="dev")
            self.assertEqual(ep.call_args.kwargs["scenario"], scenario)
            self.assertEqual(calc.call_count, 1)
            return result

    def test_units_versions_no_grade_and_adjusted_dps(self):
        result = self.evaluate()
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["scenario"]["enemy_level_shift"], 4)
        self.assertEqual(result["versions"]["database_version"], "test-123")
        self.assertEqual(result["stage"], "measurements_only")
        self.assertNotIn("ratings", result)
        off = result["measurements"]["offense"]
        self.assertEqual(off["single_target_dps_raw"]["value"], 100)
        self.assertEqual(off["scenario_personal_dps"]["value"], 43)
        self.assertEqual(off["scenario_personal_dps"]["unit"], "damage_per_second_equivalent")
        self.assertEqual(result["measurements"]["support"]["enemy_debuff_percent_by_effect"]["Regeneration"], 50)

    def test_explicit_general_retains_plus_one(self):
        self.assertEqual(self.evaluate(scenario="general")["scenario"]["enemy_level_shift"], 1)
        self.assertEqual(self.evaluate()["scenario"]["enemy_level_shift"], 4)

    def test_build_is_not_mutated(self):
        before = copy.deepcopy(self.build)
        self.evaluate()
        self.assertEqual(self.build, before)

    def test_unknown_powers_are_disclosed(self):
        build = copy.deepcopy(self.build)
        build["powers"].append({"full_name": "No.Such.Power", "slots": []})
        result = self.evaluate(build=build)
        self.assertEqual(result["unsupported"]["unknown_power_records"], ["No.Such.Power"])
        self.assertEqual(result["unsupported"]["effect_level_audit"], "not_implemented")

    def test_invalid_inputs_rejected(self):
        for scenario in ("bad", None, {"id": "general"}):
            with self.subTest(scenario=scenario), \
                    self.assertRaisesRegex(ValueError, "Unknown evaluation scenario"):
                self.evaluate(scenario=scenario)
        with self.assertRaisesRegex(ValueError, "Each power"):
            self.evaluate(build=dict(self.build, powers=[None]))
        with self.assertRaisesRegex(ValueError, "powers array"):
            self.evaluate(build=dict(self.build, powers=None))
        with self.assertRaisesRegex(ValueError, "archetype"):
            self.evaluate(build=dict(self.build, archetype="Nonsense"))

    def test_missing_numeric_outputs_never_coerce_to_zero(self):
        self.totals["offense"].pop("st_dps")
        row = self.evaluate()["measurements"]["offense"]["single_target_dps_raw"]
        self.assertIsNone(row["value"])
        self.assertEqual(row["status"], "unknown")

    def test_nonfinite_numeric_is_not_serialized_as_json_nan(self):
        row = ev._measurement(float("nan"), "percent", "test")
        self.assertEqual(row["status"], "unknown")
        self.assertIsNone(row["value"])


if __name__ == "__main__":
    unittest.main()
