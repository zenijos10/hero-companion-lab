"""Battery for the toughness grades (server/survival_profile.py): the damage a
build can take per type and position, and its multiple of a bare archetype.

Pins the arithmetic on hand-made totals (a bare character reads exactly 1x; the
even mix is the harmonic mean of the cells; defense is the best of position and
type; resistance caps at 90%; a hole in one type moves only that type), then,
through the REAL /build/evaluate route, that the measurement and both grades are
there and that removing the armor powers lowers toughness (negative control).

Run: python tools/test_survival_profile.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-tough-"))

import first_principles as fp  # noqa: E402
import survival_profile as surv  # noqa: E402

SC = dict(fp.SCENARIOS["general"], shift=4)
HP = 1200.0


def totals(defense=None, resistance=None):
    row = lambda rows: {k: {"value": v} for k, v in (rows or {}).items()}  # noqa: E731
    return {"defense": row(defense), "resistance": row(resistance)}


def inputs(hp=HP, regen=None, heal=0.0, absorb=0.0, tohit=0.0, ddr=0.0):
    return {"hp": hp, "regen_hps": HP * fp._REGEN_PER_SEC if regen is None else regen,
            "self_heal_hps": heal, "absorb_hps": absorb, "tohit_debuff": tohit,
            "def_debuff_in": ddr}


def cells(p):
    return [v for row in p["grid"].values() for v in row.values()]


class ArithmeticTests(unittest.TestCase):
    def test_bare_character_is_one_times_its_archetype(self):
        p = surv.profile(totals(), inputs(), SC, HP, 30.0)
        self.assertEqual(p["vs_archetype"], 1.0)
        self.assertEqual(p["toughness"], p["bare_archetype"])
        self.assertEqual(len(set(cells(p))), 1)

    def test_even_mix_is_the_harmonic_mean_of_the_cells(self):
        p = surv.profile(totals({"Melee": 30, "Fire": 20}, {"Smashing": 40, "Psionic": 10}),
                         inputs(heal=5.0), SC, HP, 30.0)
        values = cells(p)
        harmonic = len(values) / sum(1.0 / v for v in values)
        self.assertAlmostEqual(p["toughness"], harmonic, delta=0.2)
        self.assertEqual(p["weakest"]["value"], min(values))

    def test_defense_is_the_best_of_position_and_type(self):
        p = surv.profile(totals({"Melee": 30, "Fire": 20}), inputs(), SC, HP, 30.0)
        g = p["grid"]
        self.assertEqual(g["Melee"]["Cold"], g["Melee"]["Fire"])     # Melee 30 beats Fire 20
        self.assertGreater(g["Ranged"]["Fire"], g["Ranged"]["Cold"])  # only Fire applies
        self.assertGreater(g["Melee"]["Cold"], g["Ranged"]["Fire"])

    def test_resistance_caps_at_ninety(self):
        capped = surv.profile(totals(resistance={"Fire": 90}), inputs(), SC, HP, 30.0)
        over = surv.profile(totals(resistance={"Fire": 120}), inputs(), SC, HP, 30.0)
        self.assertEqual(capped["grid"]["AoE"]["Fire"], over["grid"]["AoE"]["Fire"])

    def test_a_hole_moves_only_its_type(self):
        a = surv.profile(totals(resistance={"Psionic": 0}), inputs(), SC, HP, 30.0)
        b = surv.profile(totals(resistance={"Psionic": 50}), inputs(), SC, HP, 30.0)
        for pos in surv.POSITIONS:
            for t in surv.TYPES:
                moved = b["grid"][pos][t] != a["grid"][pos][t]
                self.assertEqual(moved, t == "Psionic", (pos, t))

    def test_sustain_and_debuffs_count(self):
        base = surv.profile(totals(), inputs(), SC, HP, 30.0)["toughness"]
        for kw in ({"heal": 10.0}, {"absorb": 10.0}, {"tohit": 0.1}):
            self.assertGreater(surv.profile(totals(), inputs(**kw), SC, HP, 30.0)["toughness"],
                               base, kw)
        eroded = surv.profile(totals({"Melee": 30}), inputs(ddr=0.1), SC, HP, 30.0)
        whole = surv.profile(totals({"Melee": 30}), inputs(), SC, HP, 30.0)
        self.assertLess(eroded["grid"]["Melee"]["Fire"], whole["grid"]["Melee"]["Fire"])


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        cls.client = srv.app.test_client()
        at, p, s = "Class_Tanker", "Tanker_Defense.Invulnerability", "Tanker_Melee.Super_Strength"
        picks = cls.client.post("/build/autopick", json={"archetype": at, "primary": p,
                                                         "secondary": s}).get_json()
        build = {"archetype": at, "primary": p, "secondary": s, "powers": picks["powers"]}
        solved = cls.client.post("/build/solve", json=build).get_json()
        build["powers"] = solved.get("powers") or build["powers"]
        cls.build, cls.primary = build, p

    def evaluate(self, build):
        return self.client.post("/build/evaluate", json={"build": build}).get_json()

    def test_measurement_and_both_grades(self):
        ev = self.evaluate(self.build)
        sv = ev["measurements"]["survival"]
        t = sv["toughness"]
        grid = [v for row in t["by_position_and_type"].values() for v in row.values()]
        self.assertEqual(len(grid), 24)
        self.assertTrue(min(grid) <= t["value"] <= max(grid))
        self.assertAlmostEqual(sv["toughness_vs_archetype"]["value"],
                               t["value"] / t["bare_archetype"], delta=0.01)
        cats = ev["ratings"]["categories"]
        for key in ("toughness", "toughness_vs_archetype"):
            self.assertIn(cats[key]["grade"], tuple("SABCDF"), key)
        self.assertIn("weakest", cats["toughness"]["detail"])
        print(f"Invuln/SS Tanker: toughness {t['value']} ({cats['toughness']['grade']}), "
              f"{sv['toughness_vs_archetype']['value']}x bare "
              f"({cats['toughness_vs_archetype']['grade']})")

    def test_removing_the_armor_lowers_toughness(self):
        bare = dict(self.build, powers=[p for p in self.build["powers"]
                                        if not p["full_name"].startswith(self.primary)])
        full = self.evaluate(self.build)["measurements"]["survival"]
        less = self.evaluate(bare)["measurements"]["survival"]
        self.assertLess(less["toughness"]["value"], full["toughness"]["value"])
        self.assertLess(less["toughness_vs_archetype"]["value"],
                        full["toughness_vs_archetype"]["value"])


if __name__ == "__main__":
    unittest.main()
