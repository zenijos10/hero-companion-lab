"""M2: /build/evaluate on REAL builds, through the real routes (no stubs).

Each build is generated the way the app makes one (autopick, then the real
/build/solve) on the shipped game data, then evaluated. Covers pets (MM),
controls (Controller), incarnates + an emergency click (Brute), and a redirect
power the model cannot read (Archery Blaster). When the pinned Sidekick
contract checkout is present (CI), the real Sidekick v5 fixture is imported
and evaluated too.

Run: python tools/test_build_evaluation_builds.py
"""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-evaluation-builds-"))

import server as srv  # noqa: E402

CONTRACT = ROOT / "_sidekick_contract_fixture"
UNSTOPPABLE = "Brute_Defense.Invulnerability.Unstoppable"
RANGED_SHOT = "Blaster_Ranged.Archery.Ranged_Shot"

CASES = {
    "mastermind": ("Class_Mastermind", "Mastermind_Summon.Mercenaries",
                   "Mastermind_Buff.Force_Field"),
    "controller": ("Class_Controller", "Controller_Control.Mind_Control",
                   "Controller_Buff.Kinetics"),
    "brute": ("Class_Brute", "Brute_Melee.Super_Strength", "Brute_Defense.Invulnerability"),
    "archer": ("Class_Blaster", "Blaster_Ranged.Archery", "Blaster_Support.Tactical_Arrow"),
    "cold": ("Class_Defender", "Defender_Buff.Cold_Domination", "Defender_Ranged.Ice_Blast"),
    "forcefield": ("Class_Defender", "Defender_Buff.Force_Field", "Defender_Ranged.Energy_Blast"),
    "poison": ("Class_Corruptor", "Corruptor_Ranged.Fire_Blast", "Corruptor_Buff.Poison"),
}
BENUMB = "Defender_Buff.Cold_Domination.Benumb"


def _scalars(node, path=""):
    """Every {value, unit, status} measurement in a response, with its path."""
    if isinstance(node, dict):
        if {"value", "unit", "status"} <= node.keys():
            yield path, node
        for key, child in node.items():
            yield from _scalars(child, f"{path}.{key}")
    elif isinstance(node, list):
        for i, child in enumerate(node):
            yield from _scalars(child, f"{path}[{i}]")


class RealBuildEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = srv.app.test_client()
        cls.builds = {name: cls._generate(*sets) for name, sets in CASES.items()}
        # Validate the generated builds BEFORE the probes below append powers:
        # those additions make the brute/archer/mastermind cases measurement probes, not
        # guaranteed-legal characters (a 25th pick is not something we claim).
        cls.validation = {name: cls.client.post("/build/validate", json=dict(
            b, powers=[dict(p) for p in b["powers"]])).get_json()
            for name, b in cls.builds.items()}
        brute = cls.builds["brute"]
        if UNSTOPPABLE not in {p["full_name"] for p in brute["powers"]}:
            brute["powers"].append({"full_name": UNSTOPPABLE, "slots": [None]})
        brute["include_incarnates"] = True
        mastermind = cls.builds["mastermind"]       # autopick leaves the upgrades out
        for upgrade in ("Mastermind_Summon.Mercenaries.Equip_Mercenary",
                        "Mastermind_Summon.Mercenaries.Tactical_Upgrade"):
            if upgrade not in {p["full_name"] for p in mastermind["powers"]}:
                mastermind["powers"].append({"full_name": upgrade, "slots": []})
        cold = cls.builds["cold"]
        if BENUMB not in {p["full_name"] for p in cold["powers"]}:
            cold["powers"].append({"full_name": BENUMB, "slots": [None]})
        archer = cls.builds["archer"]
        if RANGED_SHOT not in {p["full_name"] for p in archer["powers"]}:
            archer["powers"].append({"full_name": RANGED_SHOT, "slots": [None]})

    @classmethod
    def _generate(cls, archetype, primary, secondary):
        ap = cls.client.post("/build/autopick", json={
            "archetype": archetype, "primary": primary, "secondary": secondary,
            "content": "general"}).get_json()
        assert ap and ap.get("ok"), (archetype, ap)
        solved = cls.client.post("/build/solve", json={
            "archetype": archetype, "content": "general", "tier": "premium",
            "preserve": False, "powers": ap["powers"]}).get_json()
        assert solved and solved.get("ok"), (archetype, solved)
        return {"archetype": archetype, "primary": primary, "secondary": secondary,
                "powers": solved["powers"]}

    def test_generated_builds_validate_before_the_probe_additions(self):
        for name, result in self.validation.items():
            with self.subTest(build=name):
                self.assertIn("errors", result, str(result)[:200])
                self.assertEqual(result["errors"], [], str(result)[:400])

    def evaluate(self, build, scenario=None):
        body = {"build": build} if scenario is None else {"build": build, "scenario": scenario}
        response = self.client.post("/build/evaluate", json=body)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
        return response.get_json()

    def test_every_measurement_is_finite_or_explicitly_unknown(self):
        for name, build in self.builds.items():
            with self.subTest(build=name):
                data = self.evaluate(build)
                json.dumps(data, allow_nan=False)          # no NaN/inf reaches JSON
                rows = list(_scalars(data["measurements"]))
                self.assertGreater(len(rows), 20)
                for path, row in rows:
                    if row["status"] == "modeled":
                        self.assertTrue(math.isfinite(row["value"]), path)
                    else:
                        self.assertIsNone(row["value"], path)

    def test_repeated_evaluations_are_identical(self):
        for name, build in self.builds.items():
            with self.subTest(build=name):
                self.assertEqual(self.evaluate(build), self.evaluate(build))

    def test_scenario_parts_sum_to_the_personal_contribution(self):
        """0.4 x ST + 0.6 x AoE x targets + pets IS encounter_value's my_dps."""
        for name, build in self.builds.items():
            with self.subTest(build=name):
                off = self.evaluate(build)["measurements"]["offense"]
                parts = (0.4 * off["scenario_single_target_dps"]["value"]
                         + 0.6 * off["scenario_aoe_targets"]
                         * off["scenario_aoe_dps_per_target"]["value"]
                         + off["scenario_pet_dps"]["value"])
                self.assertAlmostEqual(parts, off["scenario_personal_dps"]["value"], delta=0.6)

    def test_plus_four_hits_less_than_plus_one(self):
        build = self.builds["brute"]
        plus4 = self.evaluate(build)["measurements"]
        plus1 = self.evaluate(build, "general")["measurements"]
        self.assertLess(plus4["survival"]["outgoing_hit"]["value"],
                        plus1["survival"]["outgoing_hit"]["value"])
        self.assertLess(plus4["offense"]["scenario_single_target_dps"]["value"],
                        plus1["offense"]["scenario_single_target_dps"]["value"])

    def test_mastermind_pets_are_measured(self):
        off = self.evaluate(self.builds["mastermind"])["measurements"]["offense"]
        self.assertGreater(off["scenario_pet_dps"]["value"], 0)

    def test_controller_control_is_measured(self):
        support = self.evaluate(self.builds["controller"])["measurements"]["support"]
        self.assertGreater(support["control_proxy"]["value"], 0)
        self.assertTrue(support["control_by_power"])

    def test_emergency_click_is_separate_from_sustained(self):
        data = self.evaluate(self.builds["brute"])
        rows = {r["power"]: r for r in data["measurements"]["survival"]["emergency_powers"]}
        self.assertIn(UNSTOPPABLE, rows)
        row = rows[UNSTOPPABLE]
        self.assertTrue(row["while_active_gain_percent_points"]["resistance"])
        self.assertLess(row["uptime"]["value"], 1.0)
        self.assertTrue(row["penalties"], "Unstoppable's crash is in the data")
        # ticking it does not move the sustained resistance
        ticked = json.loads(json.dumps(self.builds["brute"]))
        for p in ticked["powers"]:
            if p["full_name"] == UNSTOPPABLE:
                p["include_in_totals"] = True
        again = self.evaluate(ticked)
        self.assertEqual(again["measurements"]["survival"]["resistance"],
                         data["measurements"]["survival"]["resistance"])
        self.assertEqual(again["inputs_normalized"]["emergency_excluded_from_sustained"],
                         [UNSTOPPABLE])

    def test_unreadable_redirect_power_is_disclosed(self):
        data = self.evaluate(self.builds["archer"])
        reasons = {(u["power"], u["reason"]) for u in data["unsupported"]["powers"]}
        self.assertIn((RANGED_SHOT, "unread_redirect"), reasons)
        conf = data["confidence"]
        self.assertLess(conf["powers_read"]["value"], conf["powers_total"])
        self.assertIs(conf["offense_complete"], False)   # a damaging power is unread

    def test_mastermind_upgrades_are_modeled_elsewhere(self):
        data = self.evaluate(self.builds["mastermind"])
        unread = {u["power"] for u in data["unsupported"]["powers"]
                  if u["reason"] in ("unread_redirect", "no_effect_rows")}
        elsewhere = {m["power"] for m in data["unsupported"]["modeled_without_effect_rows"]}
        self.assertTrue(elsewhere, "a Mercenaries MM picks its upgrade powers")
        self.assertFalse(unread & elsewhere)

    def test_invulnerability_mez_protection_is_disclosed(self):
        reasons = {u["reason"] for u in self.evaluate(self.builds["brute"])["unsupported"]["powers"]}
        self.assertIn("mez_protection_not_scored", reasons)

    def support(self, name):
        return self.evaluate(self.builds[name])["measurements"]["support"]["team_support"]

    def test_av_single_target_regen_debuffer_is_recognized(self):
        """M3 acceptance: strong ST -regen vs an AV, without AoE -damage, is visible."""
        summary = self.support("cold")["summary"]["debuffs_landing_average_percent"]
        st_regen = summary["single_target_vs_av"].get("Regeneration", 0.0)
        self.assertGreater(st_regen, 10.0, summary)
        self.assertGreater(st_regen, summary["aoe_vs_scenario"].get("DamageBuff", 0.0))

    def test_defensive_buffer_is_credited_without_healing(self):
        """M3 acceptance: a high-uptime defense buffer reads high with low healing."""
        summary = self.support("forcefield")["summary"]
        self.assertGreater(summary["buffs_average_percent"]["sustained"].get("Defense", 0.0), 20.0)
        self.assertEqual(summary["ally_heals"]["sustained_per_second"], 0.0)

    def test_resistance_debuff_ignores_av_debuff_resistance(self):
        """AVs resist every debuff except -Resistance (scenario av debuff_res)."""
        rows = [d for e in self.support("cold")["powers"] for d in e.get("debuffs") or []]
        res = [d for d in rows if d["effect"] == "Resistance"]
        other = [d for d in rows if d["effect"] == "Regeneration"]
        self.assertTrue(res and other)
        for d in res:
            self.assertAlmostEqual(d["landing_peak_percent"]["vs_av"], round(d["peak_percent"] * 0.8, 2),
                                   delta=0.02)
        for d in other:
            self.assertLess(d["landing_peak_percent"]["vs_av"], d["peak_percent"] * 0.8 * 0.2)

    def test_rez_buffs_and_instant_effects_stay_out_of_averages(self):
        ledger = self.support("poison")
        elixir = [e for e in ledger["powers"] if e["power"].endswith("Elixir_of_Life")]
        self.assertTrue(elixir, "the Poison build picks Elixir of Life (a rez)")
        self.assertIn("conditional", elixir[0])
        self.assertNotIn("RechargeTime", ledger["summary"]["buffs_average_percent"]["sustained"])
        for e in ledger["powers"]:
            for d in (e.get("debuffs") or []) + (e.get("buffs") or []):
                if d["instant"]:
                    self.assertIsNone(d["average_percent"])

    def test_support_entries_carry_coverage_and_cost(self):
        for e in self.support("cold")["powers"]:
            self.assertIn(e["area"], ("aoe", "single_target"))
            self.assertGreaterEqual(e["cost"]["endurance_per_minute"], 0.0)
            for c in e.get("controls") or []:
                self.assertTrue(set(c["affects_in_one_application"]) <=
                                {"minion", "lieutenant", "boss", "elite_boss", "archvillain"})

    @unittest.skipUnless((CONTRACT / "fixtures/skif/v5/rb5d_browser_pass.skif").is_file(),
                         "pinned Sidekick contract checkout not present (CI provides it)")
    def test_real_sidekick_build_imports_and_evaluates(self):
        source = (CONTRACT / "fixtures/skif/v5/rb5d_browser_pass.skif").read_text(encoding="utf-8")
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        env = {"HC_SIDEKICK_CONTRACT_DIR": str(CONTRACT / "contract/homecoming")}
        with patch.dict(os.environ, env), \
                patch.object(srv, "_sidekick_cache_dir", return_value=Path(cache.name)):
            imported = self.client.post("/build/import-sidekick",
                                        json={"skif": source}).get_json()
        self.assertTrue(imported.get("ok"), str(imported)[:400])
        build = imported["build"]
        data = self.evaluate(build)
        self.assertEqual(data["build"]["archetype"], build["archetype"])
        self.assertEqual(data["unsupported"]["unknown_power_records"], [])
        json.dumps(data, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
