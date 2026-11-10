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

    def evaluate(self, *, build=None, scenario="rating_plus4", out_of_combat=None):
        def calculate(b, *_a, **_k):
            self.calc_builds.append(copy.deepcopy(b))
            if b.get("suppression") is False and out_of_combat is not None:
                return out_of_combat
            return self.totals
        self.calc_builds = []
        with patch.object(ev.first_principles, "SCENARIOS", self.scenarios), \
             patch.object(ev.engine, "calculate_build", side_effect=calculate) as calc, \
             patch.object(ev.first_principles, "encounter_value", return_value=self.encounter) as ep, \
             patch.object(ev.role_output, "build_control_output",
                          return_value=(25.0, [("Hold", 25.0)])), \
             patch.object(ev.role_output, "build_control_uptime",
                          return_value={"controls": []}), \
             patch.object(ev.role_output, "build_heal_output",
                          return_value={"team_hps": 1, "self_hps": 2, "rez": 0}), \
             patch.object(ev.role_output, "enhanced_debuff_totals",
                          return_value={"Regeneration": 50}) as debuffs, \
             patch.object(ev.role_output, "enhanced_team_buffs",
                          return_value={"Defense": 15}):
            result = ev.evaluate(self.build if build is None else build, scenario,
                                 ctx=self.ctx, set_bonuses={}, res_cap=75,
                                 archetype_record={"name": "Class_Test", "hitpoints": 1000},
                                 db_name="Homecoming", db_version="test-123",
                                 app_version="dev")
            self.assertEqual(ep.call_args.kwargs["scenario"], scenario)
            # in combat, plus one pass per emergency power and one out of combat
            # when a suppressible effect exists (test_no_out_of_combat_pass pins 1)
            self.assertGreaterEqual(calc.call_count, 2 if out_of_combat is not None else 1)
            self.encounter_kwargs = ep.call_args.kwargs
            self.debuff_recharge = debuffs.call_args.kwargs["global_recharge"]
            return result

    def test_units_versions_no_grade_and_adjusted_dps(self):
        result = self.evaluate()
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["scenario"]["enemy_level_shift"], 4)
        self.assertEqual(result["versions"]["database_version"], "test-123")
        self.assertEqual(result["stage"], "measurements_and_ratings")
        # no thresholds passed: the contract says why instead of grading
        self.assertEqual(result["ratings"]["status"], "not_rated")
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
        self.assertEqual(result["unsupported"]["effect_level_audit"], "power_level")

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

    def test_support_recharge_includes_hasten_like_encounter_value(self):
        self.evaluate()
        self.assertAlmostEqual(self.debuff_recharge, 0.5)          # no Hasten: passive only
        build = copy.deepcopy(self.build)
        build["powers"].append({"full_name": "Pool.Speed.Hasten", "slots": []})
        result = self.evaluate(build=build)
        want = 0.5 + ev.first_principles.hasten_recharge_average(build["powers"], 0.5)
        self.assertGreater(want, 0.5)
        self.assertAlmostEqual(self.debuff_recharge, want)
        self.assertGreater(result["measurements"]["resources"]["hasten_average_recharge"]["value"], 0)

    def test_pvp_and_exemplar_follow_calculate_semantics(self):
        with self.assertRaisesRegex(ValueError, "PvP"):
            self.evaluate(build=dict(self.build, pvp=True))
        with self.assertRaisesRegex(ValueError, "Exemplar"):
            self.evaluate(build=dict(self.build, exemplar_level=35))
        for level in (50, 0, "", None, 99, "abc"):     # /build/calculate: no exemplar
            with self.subTest(level=level):
                self.assertTrue(self.evaluate(build=dict(self.build, exemplar_level=level))["ok"])

    def test_owned_boosters_are_rated_and_external_buffs_removed(self):
        build = copy.deepcopy(self.build)
        build["powers"][0]["slots"] = [{"piece_uid": "X", "boost": 5}, None,
                                       {"piece_uid": "Y", "boost": 0},
                                       {"piece_uid": "Z", "boost": -2}]
        build["include_external"] = True
        build["include_amplifiers"] = True      # both set: neither may survive
        result = self.evaluate(build=build)
        rated = self.calc_builds[0]
        self.assertEqual([s and s.get("boost") for s in rated["powers"][0]["slots"]],
                         [5, None, 0, -2])      # owned levels (and below-level IOs) kept
        self.assertNotIn("include_external", rated)
        self.assertNotIn("include_amplifiers", rated)
        self.assertIs(rated["suppression"], True)
        self.assertEqual(result["inputs_normalized"],
                         {"boosted_pieces_rated": 1, "external_buffs_removed": True,
                          "defense_basis": "in_combat",
                          "emergency_excluded_from_sustained": []})
        self.assertNotIn("suppression", build)   # caller untouched

    def test_defense_is_in_combat_with_out_of_combat_companion(self):
        self.ctx["power_by_full"]["Test.One.Power"] = {
            "self_effects": [{"suppression": ev.engine.SUPPRESS_IN_COMBAT}]}
        ooc = dict(self.totals, defense={"Melee": {"value": 45.0}, "AoE": {"value": 88.0}})
        self.totals["defense"] = {"Melee": {"value": 45.0}, "AoE": {"value": 10.0}}
        survival = self.evaluate(out_of_combat=ooc)["measurements"]["survival"]
        self.assertEqual(survival["defense"]["AoE"]["value"], 10.0)
        self.assertEqual(list(survival["defense_out_of_combat"]), ["AoE"])
        self.assertEqual(survival["defense_out_of_combat"]["AoE"]["value"], 88.0)

    def test_scenario_constants_are_fingerprinted(self):
        first = self.evaluate()
        self.assertEqual(self.encounter_kwargs["scenario_params"]["shift"], 4)
        self.scenarios["general"]["enemies"] = 5        # tune a constant, no version bump
        second = self.evaluate()
        self.assertNotEqual(first["versions"]["scenario_fingerprint"],
                            second["versions"]["scenario_fingerprint"])
        self.assertEqual(second["scenario"]["parameters"]["enemies"], 5)

    def test_emergency_click_is_out_of_sustained_and_measured_alone(self):
        self.ctx["power_by_full"]["Test.One.Power"] = {
            "power_type": 0, "base_recharge": 1000.0, "display_name": "Panic",
            "self_effects": [
                {"effect": "Resistance", "damage_type": "Fire", "scale": 7.0, "duration": 180.0},
                {"effect": "Recovery", "scale": -100.0, "duration": 20.0}]}
        build = copy.deepcopy(self.build)
        build["powers"][0]["include_in_totals"] = True      # the player ticked it
        active = dict(self.totals, resistance={"Fire": {"value": 90.0}})

        def calculate(b, *_a, **_k):
            self.calc_builds.append(copy.deepcopy(b))
            return active if b["powers"][0].get("include_in_totals") else self.totals
        with patch.object(ev.engine, "calculate_build", side_effect=calculate):
            self.calc_builds = []
            result = ev.evaluate(build, "general", ctx=self.ctx, set_bonuses={}, res_cap=75,
                                 archetype_record={"name": "Class_Test"}, db_name="H",
                                 db_version="t", app_version="dev")
        self.assertIs(self.calc_builds[0]["powers"][0]["include_in_totals"], False)
        self.assertEqual(result["inputs_normalized"]["emergency_excluded_from_sustained"],
                         ["Test.One.Power"])
        (row,) = result["measurements"]["survival"]["emergency_powers"]
        self.assertEqual(row["while_active_gain_percent_points"]["resistance"], {"Fire": 15.0})
        self.assertEqual(row["duration_seconds"]["value"], 180.0)
        self.assertAlmostEqual(row["recharge_seconds"]["value"], round(1000.0 / 1.5, 1))
        self.assertAlmostEqual(row["uptime"]["value"], round(180.0 / (1000.0 / 1.5), 3))
        self.assertEqual(row["penalties"], [{"effect": "Recovery", "scale": -100.0,
                                             "duration_seconds": 20.0}])

    def test_unsupported_detail_and_confidence(self):
        self.ctx["power_by_full"].update({
            "Test.One.Power": {"full_name": "Test.One.Power", "powerset_full_name": "Test.One",
                               "level_available": 1, "pet_powersets": ["Redirects.Test"]},
            "Redirects.Test.Power_Normal": {"full_name": "Redirects.Test.Power_Normal",
                                            "powerset_full_name": "Redirects.Test",
                                            "damage_effects": [{"scale": 1.0}]},
            "Test.One.Mez": {"full_name": "Test.One.Mez", "level_available": 1,
                             "self_effects": [{"effect": "MezProtection", "scale": -50.0}]},
            "Test.One.Shot": {"full_name": "Test.One.Shot", "level_available": 1,
                              "accepted_enhancement_types": ["Damage Increase"]},
            "Test.One.Taunt": {"full_name": "Test.One.Taunt", "level_available": 1,
                               "accepted_enhancement_types": ["Taunt Duration"]},
            "Test.One.Stance": {"full_name": "Test.One.Stance", "level_available": 1}})
        build = copy.deepcopy(self.build)
        build["powers"] += [{"full_name": n, "slots": []} for n in (
            "Test.One.Mez", "Test.One.Shot", "Test.One.Taunt", "Test.One.Stance", "No.Such.Power")]
        result = self.evaluate(build=build)
        rows = {(u["power"], u["reason"]): u for u in result["unsupported"]["powers"]}
        self.assertEqual(set(rows), {("Test.One.Power", "unread_redirect"),
                                     ("Test.One.Mez", "mez_protection_not_scored"),
                                     ("Test.One.Shot", "damaging_unread"),
                                     ("Test.One.Taunt", "effect_unread"),
                                     ("Test.One.Stance", "unpriced_mechanic"),
                                     ("No.Such.Power", "unknown_record")})
        self.assertEqual(rows[("Test.One.Power", "unread_redirect")]["twins"],
                         ["Redirects.Test.Power_Normal"])
        self.assertIs(rows[("Test.One.Power", "unread_redirect")]["damaging"], True)
        conf = result["confidence"]
        # read: Mez (has effects) and Stance (a mechanic: nothing to read)
        self.assertEqual((conf["powers_read"]["value"], conf["powers_total"]), (2, 6))
        self.assertIs(conf["offense_complete"], False)
        self.assertIn("provisional", conf["sections"]["scenario"])

    def test_non_damaging_gaps_leave_offense_complete(self):
        self.ctx["power_by_full"]["Test.One.Power"] = {
            "full_name": "Test.One.Power", "level_available": 1,
            "accepted_enhancement_types": ["Taunt Duration"]}
        conf = self.evaluate()["confidence"]
        self.assertIs(conf["offense_complete"], True)
        self.assertEqual(conf["powers_read"]["value"], 0)

    def test_mastermind_upgrade_is_modeled_elsewhere_not_unread(self):
        """Effect-less, yet encounter_value prices it by cast time (shared rule)."""
        self.ctx["power_by_full"].update({
            "Test.One.Power": {"full_name": "Test.One.Power", "level_available": 1,
                               "powerset_full_name": "Mastermind_Summon.Bots", "summons": ["Pet"]},
            "Test.One.Upgrade": {"full_name": "Test.One.Upgrade", "level_available": 1,
                                 "powerset_full_name": "Mastermind_Summon.Bots", "cast_time": 2.0}})
        build = copy.deepcopy(self.build)
        build["powers"].append({"full_name": "Test.One.Upgrade", "slots": []})
        result = self.evaluate(build=build)
        self.assertEqual([u["power"] for u in result["unsupported"]["powers"]], [])
        self.assertEqual([m["power"] for m in result["unsupported"]["modeled_without_effect_rows"]],
                         ["Test.One.Upgrade"])
        self.assertEqual(result["confidence"]["powers_read"]["value"], 2)

    def test_a_summon_outside_mastermind_sets_makes_no_upgrades(self):
        """Storm Blast has a summon; its effect-less Direct Strike is an attack."""
        self.ctx["power_by_full"].update({
            "Test.One.Power": {"full_name": "Test.One.Power", "level_available": 1,
                               "powerset_full_name": "Blaster_Ranged.Storm", "summons": ["Pet"]},
            "Test.One.Strike": {"full_name": "Test.One.Strike", "level_available": 1,
                                "powerset_full_name": "Blaster_Ranged.Storm", "cast_time": 1.0,
                                "accepted_enhancement_types": ["Damage Increase"]}})
        build = copy.deepcopy(self.build)
        build["powers"].append({"full_name": "Test.One.Strike", "slots": []})
        result = self.evaluate(build=build)
        self.assertEqual(result["unsupported"]["modeled_without_effect_rows"], [])
        self.assertIn(("Test.One.Strike", "damaging_unread"),
                      {(u["power"], u["reason"]) for u in result["unsupported"]["powers"]})

    def test_emergency_uptime_is_per_effect_when_durations_differ(self):
        self.ctx["power_by_full"]["Test.One.Power"] = {
            "power_type": 0, "base_recharge": 300.0,
            "self_effects": [
                {"effect": "Defense", "damage_type": "Melee", "scale": 5.0, "duration": 90.0},
                {"effect": "Resistance", "damage_type": "Fire", "scale": 5.0, "duration": 30.0}]}
        (row,) = self.evaluate()["measurements"]["survival"]["emergency_powers"]
        self.assertIs(row["uniform_duration"], False)
        rech = 300.0 / 1.5
        self.assertEqual(row["uptime_by_effect"],
                         {"Defense.Melee": round(90 / rech, 3), "Resistance.Fire": round(30 / rech, 3)})

    def test_scenario_st_aoe_and_pets_are_reported_separately(self):
        self.encounter.update(st_dps_scenario=30.0, aoe_dps_scenario_per_target=5.0,
                              aoe_targets=4, pet_dps_scenario=7.0)
        off = self.evaluate()["measurements"]["offense"]
        self.assertEqual(off["scenario_single_target_dps"]["value"], 30.0)
        self.assertEqual(off["scenario_aoe_dps_per_target"]["value"], 5.0)
        self.assertEqual(off["scenario_aoe_targets"], 4)
        self.assertEqual(off["scenario_pet_dps"]["value"], 7.0)

    def test_no_out_of_combat_pass_without_suppressible_effects(self):
        survival = self.evaluate()["measurements"]["survival"]
        self.assertEqual(len(self.calc_builds), 1)
        self.assertEqual(survival["defense_out_of_combat"], {})

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
