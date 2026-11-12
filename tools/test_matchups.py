"""Battery for VS enemy group (server/matchups.py) and its data
(data/critter_groups.json, written by tools/fetch_critter_data.py).

Pins the compiled data (coverage, mixes that sum to one, no allied or event
groups, the all-groups cascade constants copied into the rating scenario), the
critter parser on a real City of Data record shape, the matchup arithmetic (a
hole in the group's damage type shortens time to live, DDR shrinks the
cascade, defense lost never exceeds the defense the build has, the group's
resistance cuts your damage), and the real route (every group rated, hardest
first, a Tanker outlasting groups a Blaster does not).

Run: python tools/test_matchups.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "tools")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-matchups-"))

import build_evaluation  # noqa: E402
import fetch_critter_data as fetch  # noqa: E402
import matchups  # noqa: E402

DATA = json.loads((ROOT / "data" / "critter_groups.json").read_text(encoding="utf-8"))
SC = build_evaluation.scenario_params("rating_plus4")
EXPECTED_GROUPS = 106


def totals(defense=None, resistance=None, ddr=0.0):
    row = lambda rows: {k: {"value": v} for k, v in (rows or {}).items()}  # noqa: E731
    return {"defense": row(defense), "resistance": row(resistance),
            "bonus_extras": {"def_debuff_resist": {"value": ddr}}}


INPUTS = {"hp": 1500.0, "regen_hps": 5.0, "self_heal_hps": 0.0, "absorb_hps": 0.0,
          "tohit_debuff": 0.0, "def_debuff_in": 0.0}


def group(mix, def_share=0.2, res=None):
    return {"damage_mix": mix, "rank_accuracy": 1.1, "dps_per_critter": 60.0,
            "attacks_per_second_per_critter": 0.45,
            "def_debuff": {"attack_share": def_share, "percent_per_hit": 10.0, "seconds": 8.0},
            "resistances": res or {}, "mez": ["Held"]}


class DataTests(unittest.TestCase):
    def test_coverage_and_shape(self):
        groups = DATA["groups"]
        print(f"{len(groups)} of {EXPECTED_GROUPS} expected enemy groups compiled "
              f"(City of Data {DATA['revision']})")
        self.assertEqual(len(groups), EXPECTED_GROUPS)
        for name, g in groups.items():
            self.assertAlmostEqual(sum(g["damage_mix"].values()), 1.0, delta=0.02, msg=name)
            for key in g["damage_mix"]:
                pos, dtype = key.split("|")
                self.assertIn(pos, fetch.POSITIONS, name)
                self.assertIn(dtype, fetch.TYPES.values(), name)
            self.assertTrue(all(0 <= v <= 100 for v in g["resistances"].values()), name)
        self.assertFalse(set(groups) & fetch.NOT_ENEMY_GROUPS)

    def test_rating_scenario_uses_the_data(self):
        mean = DATA["all_groups_mean"]
        for key in ("enemy_attacks_per_second", "def_debuff_attack_share",
                    "def_debuff_per_hit", "def_debuff_seconds"):
            self.assertAlmostEqual(SC[key], mean[key], places=3, msg=key)


class ParserTests(unittest.TestCase):
    """A Council assault rifle shot, in City of Data's own record shape."""
    POWER = {"target_type": "Foe (Alive)", "attack_types": ["Ranged", "Lethal"],
             "activation_time": 1.0, "recharge_time": 3.0, "effects": [{
                 "chance": 1.0, "is_pvp": "EITHER", "templates": [
                     {"attribs": ["Lethal_Dmg"], "aspect": "Absolute", "target": "AnyAffected",
                      "table": "Ranged_Damage", "scale": 0.27, "duration": "0.91 seconds"},
                     {"attribs": ["Base_Defense"], "aspect": "Current", "target": "AnyAffected",
                      "table": "Ranged_Debuff_Def", "scale": 1.0, "duration": "8 seconds"}]}]}
    TABLES = {"ranged_damage": [-72.9] * 60, "ranged_debuff_def": [-0.08] * 60}

    def test_attack_profile(self):
        a = fetch.attack_profile(self.POWER, self.TABLES)
        self.assertAlmostEqual(a["damage"]["Lethal"], 0.27 * 72.9, places=3)
        self.assertEqual(a["positions"], ["Ranged"])           # the damage type tag is not a position
        self.assertEqual(a["debuffs"], [("def_debuff", 8.0, 8.0)])
        self.assertEqual(a["cycle"], 4.0)
        self_power = dict(self.POWER, target_type="Self")
        self.assertIsNone(fetch.attack_profile(self_power, self.TABLES))

    def test_overlapping_animations_scale_down(self):
        busy = dict(self.POWER, activation_time=3.0, recharge_time=0.0)
        c = fetch.critter(["a", "b"], {"a": busy, "b": busy}, self.TABLES)
        self.assertAlmostEqual(c["attacks_per_second"], 1.0 / 3.0, places=4)   # one bar


class ArithmeticTests(unittest.TestCase):
    def test_a_hole_in_their_type_shortens_life(self):
        t = totals(resistance={"Smashing": 60})
        smash = matchups.matchup(t, INPUTS, SC, group({"Melee|Smashing": 1.0}), [])
        psi = matchups.matchup(t, INPUTS, SC, group({"Melee|Psionic": 1.0}), [])
        self.assertLess(psi["time_to_live"], smash["time_to_live"])

    def test_ddr_and_the_defense_cap(self):
        g = group({"Ranged|Lethal": 1.0}, def_share=0.5)
        bare = matchups.matchup(totals({"Ranged": 30}), INPUTS, SC, g, [])
        ddr = matchups.matchup(totals({"Ranged": 30}, ddr=80), INPUTS, SC, g, [])
        self.assertLess(ddr["steady_def_debuff"], bare["steady_def_debuff"])
        self.assertGreater(ddr["time_to_live"], bare["time_to_live"])
        self.assertLessEqual(bare["steady_def_debuff_without_ddr"], 0.30 + 1e-9)
        none = matchups.matchup(totals(), INPUTS, SC, g, [])
        self.assertEqual(none["steady_def_debuff"], 0.0)       # nothing to lose

    def test_their_resistance_cuts_your_damage(self):
        types = [{"type": "Fire", "damage_share": 0.75}, {"type": "Cold", "damage_share": 0.25}]
        m = matchups.matchup(totals(), INPUTS, SC, group({"Melee|Smashing": 1.0},
                                                         res={"Fire": 40.0}), types)
        self.assertAlmostEqual(m["your_damage_unresisted"], 0.75 * 0.6 + 0.25, places=3)

    def test_outlasting_and_order(self):
        regen = dict(INPUTS, regen_hps=10000.0)
        self.assertIsNone(matchups.matchup(totals(), regen, SC, group({"Melee|Fire": 1.0}), [])
                          ["time_to_live"])
        data = {"groups": {"Easy": group({"Melee|Smashing": 1.0}),
                           "Hard": group({"Melee|Psionic": 1.0})}}
        rows = matchups.all_matchups(totals(resistance={"Smashing": 60}), INPUTS, SC, [], data)
        self.assertEqual([r["group"] for r in rows["groups"]], ["Hard", "Easy"])
        self.assertIsNone(matchups.all_matchups(totals(), INPUTS, SC, [], {}))
        self.assertEqual(matchups.display_name("CircleOfThorns"), "Circle Of Thorns")


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        cls.c = srv.app.test_client()

    def evaluate(self, at, pri, sec):
        ap = self.c.post("/build/autopick", json={"archetype": at, "primary": pri, "secondary": sec,
                                                  "content": "general"}).get_json()
        sol = self.c.post("/build/solve", json={"archetype": at, "primary": pri, "secondary": sec,
                                                "content": "general", "tier": "premium",
                                                "preserve": False, "powers": ap["powers"]}).get_json()
        b = {"archetype": at, "primary": pri, "secondary": sec, "powers": sol["powers"]}
        return self.c.post("/build/evaluate", json={"build": b}).get_json()

    def test_every_group_rated_hardest_first(self):
        tank = self.evaluate("Class_Tanker", "Tanker_Defense.Invulnerability",
                             "Tanker_Melee.Super_Strength")["matchups"]["groups"]
        blaster = self.evaluate("Class_Blaster", "Blaster_Ranged.Fire_Blast",
                                "Blaster_Support.Fire_Manipulation")["matchups"]["groups"]
        self.assertEqual(len(tank), EXPECTED_GROUPS)
        ttl = [g["time_to_live"] for g in blaster if g["time_to_live"] is not None]
        self.assertEqual(ttl, sorted(ttl))
        outlast = lambda rows: sum(1 for g in rows if g["time_to_live"] is None)  # noqa: E731
        self.assertGreater(outlast(tank), outlast(blaster))
        print(f"Tanker outlasts {outlast(tank)} groups, Blaster {outlast(blaster)}; "
              f"hardest for the Blaster: {blaster[0]['name']} ({blaster[0]['time_to_live']} s)")


if __name__ == "__main__":
    unittest.main()
