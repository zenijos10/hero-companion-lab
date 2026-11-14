"""Battery for strengths, weaknesses and the suggested lane (server/strengths.py).

    python tools/test_strengths.py

Lane scoring from grades (None counts as zero, Unknown and N/A are skipped),
the toughness grid's stand-out types and positions, the defense-without-DDR
warning and its negative control, the resisted-damage line, the not-rated
path, and the real route: a Tanker's lane is Tank and a Fire/Fire Blaster's is
a damage lane, each with sentences that name real numbers.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "server")]

import strengths  # noqa: E402


def cat(grade, label=None):
    return {"grade": grade, "label": label or "x"}


def evaluation(categories, grid=None, groups=None, types=None, status="rated"):
    return {"ratings": {"status": status, "reason": "recalibrate", "categories": categories},
            "measurements": {"survival": {"toughness": {"by_position_and_type": grid}},
                             "offense": {"damage_types": types or []}},
            "matchups": {"groups": groups or []},
            "range_profile": {"profiles": {"overall": {"melee": 0.1, "midrange": 0.2, "range": 0.7}}}}


class LaneTests(unittest.TestCase):
    def test_scoring_and_skips(self):
        cats = {"toughness": cat("S"), "resistance": cat("A"), "defense": cat("Unknown"),
                "debuff_resist_defense": cat("None"), "healing": cat("N/A"),
                "aoe_damage": cat("D"), "strike_aoe": cat("C")}
        lanes = {lane["id"]: lane for lane in strengths.lanes(cats)}
        self.assertAlmostEqual(lanes["tank"]["average_points"], (5 + 4 + 0) / 3)   # Unknown skipped, None = 0
        self.assertEqual(lanes["tank"]["weakest_part"]["category"], "debuff_resist_defense")
        self.assertNotIn("healer", lanes)                                  # N/A only: no lane
        self.assertEqual(lanes["area"]["grade"], "C")                      # (1 + 2) / 2 = 1.5, halves up
        self.assertEqual(strengths._letter(2.5), "B")                      # not round-half-to-even
        self.assertEqual(strengths.lanes(cats)[0]["id"], "tank")

    def test_grid_stand_outs(self):
        grid = {p: {"Smashing": 900, "Lethal": 900, "Fire": 300, "Psionic": 100, "Cold": 300}
                for p in ("Melee", "Ranged", "AoE")}
        hits = strengths.taking_hits(grid)
        self.assertEqual([t["name"] for t in hits["strong_types"]], ["Lethal", "Smashing"])
        self.assertEqual([t["name"] for t in hits["weak_types"]], ["Psionic"])
        self.assertEqual(hits["strong_positions"], [])                     # every position alike
        grid["Melee"] = {k: v / 4 for k, v in grid["Melee"].items()}
        self.assertEqual([p["name"] for p in strengths.taking_hits(grid)["weak_positions"]], ["Melee"])
        self.assertIsNone(strengths.taking_hits(None))


class SummaryTests(unittest.TestCase):
    def test_defense_without_ddr_warns_and_its_control(self):
        weak = strengths.summary(evaluation({"defense": cat("A"), "debuff_resist_defense": cat("F")}))
        self.assertTrue(any("cascade" in w for w in weak["weaknesses"]))
        held = strengths.summary(evaluation({"defense": cat("A"), "debuff_resist_defense": cat("S")}))
        self.assertFalse(any("cascade" in w for w in held["weaknesses"]))
        self.assertTrue(any("defense debuffs well" in s for s in held["strengths"]))
        low_def = strengths.summary(evaluation({"defense": cat("D"), "debuff_resist_defense": cat("F")}))
        self.assertFalse(any("cascade" in w for w in low_def["weaknesses"]))   # no defense to lose

    def test_resisted_damage_and_groups(self):
        groups = [{"name": "Robots", "your_damage_unresisted": 0.5, "outlasts": False,
                   "their_damage": [{"type": "Energy"}]},
                  {"name": "Gangs", "your_damage_unresisted": 1.0, "outlasts": True, "their_damage": []}]
        s = strengths.summary(evaluation({}, groups=groups,
                                         types=[{"type": "Lethal", "damage_share": 0.9}]))
        self.assertTrue(any("Robots (50% resisted)" in w for w in s["weaknesses"]))
        self.assertTrue(any("Outlasts 1 of 2" in w and "Robots (Energy)" in w for w in s["weaknesses"]))
        clean = strengths.summary(evaluation({}, groups=groups[1:],
                                             types=[{"type": "Lethal", "damage_share": 0.9}]))
        self.assertTrue(any("no enemy group resists" in x for x in clean["strengths"]))

    def test_not_rated(self):
        s = strengths.summary(evaluation({}, status="not_rated"))
        self.assertFalse(s["rated"])
        self.assertEqual(s["reason"], "recalibrate")


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
        return self.c.post("/build/evaluate", json={"build": b}).get_json()["strengths"]

    def test_lanes_follow_the_build(self):
        tank = self.evaluate("Class_Tanker", "Tanker_Defense.Invulnerability", "Tanker_Melee.Super_Strength")
        blaster = self.evaluate("Class_Blaster", "Blaster_Ranged.Fire_Blast", "Blaster_Support.Fire_Manipulation")
        self.assertEqual(tank["lanes"][0]["id"], "tank")
        self.assertIn(blaster["lanes"][0]["id"], ("alpha", "single", "area"))
        self.assertTrue(blaster["advice"].startswith("Best lane:"))
        self.assertTrue(blaster["weaknesses"] and tank["strengths"])
        self.assertIn("range", blaster["operates"])


if __name__ == "__main__":
    unittest.main()
