"""M5 battery: /build/compare (server/build_compare.py).

Unit half: the comparison rules on stub evaluations (best cell, meaningful
gap, refused column, scorecard vs comparison, never an overall winner).
Route half: real builds through /build/compare; the route is read-only (the
saves folder and the posted builds are untouched).

Run: python tools/test_build_compare.py
"""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-compare-"))

import build_compare as bc  # noqa: E402


def stub(label, grades):
    """An evaluation whose ratings carry {category: (grade, value)}."""
    cats = {k: {"grade": g, "value": v} for k, (g, v) in grades.items()}
    return {"label": label, "error": None, "evaluation": {
        "build": {"archetype": "Class_Test", "primary": "A.B", "secondary": "C.D"},
        "scenario": {"id": "rating_plus4"}, "versions": {"model": 1},
        "confidence": {"offense_complete": True},
        "unsupported": {"powers": []},
        "ratings": {"status": "rated", "categories": cats}}}


class CompareRuleTests(unittest.TestCase):
    def row(self, result, key):
        return next(r for r in result["rows"] if r["category"] == key)

    def test_scorecard_mode_for_one_build(self):
        result = bc.compare([stub("one", {"defense": ("B", 30.0)})])
        self.assertEqual(result["mode"], "scorecard")
        self.assertIsNone(self.row(result, "defense")["best"])

    def test_best_and_meaningful(self):
        result = bc.compare([stub("a", {"defense": ("B", 30.0), "recharge": ("A", 70.0)}),
                             stub("b", {"defense": ("S", 45.0), "recharge": ("A", 72.0)})])
        self.assertEqual(result["mode"], "comparison")
        defense = self.row(result, "defense")
        self.assertEqual((defense["best"], defense["meaningful"], defense["difference"]), ([1], True, 15.0))
        recharge = self.row(result, "recharge")           # same grade, 2.8% gap: not flagged
        self.assertEqual((recharge["best"], recharge["meaningful"]), ([1], False))

    def test_ties_and_non_letters_name_no_leader(self):
        result = bc.compare([stub("a", {"defense": ("B", 30.0), "control": ("None", 0.0)}),
                             stub("b", {"defense": ("B", 30.0), "control": ("A", 50.0)})])
        self.assertIsNone(self.row(result, "defense")["best"])
        self.assertIsNone(self.row(result, "control")["best"])   # only one letter-graded cell

    def test_refused_build_is_a_column_with_its_reason(self):
        refused = {"label": "pvp", "evaluation": None, "error": "PvP evaluation is not supported"}
        result = bc.compare([stub("a", {"defense": ("B", 30.0)}), refused])
        self.assertTrue(result["ok"])
        self.assertEqual(result["columns"][1], {"label": "pvp", "ok": False,
                                                "error": "PvP evaluation is not supported"})

    def test_scope_states_what_is_compared(self):
        def entry(label, at, pri, sec, picked=None):
            e = stub(label, {"defense": ("B", 30.0)})
            e["evaluation"]["build"] = {"archetype": at, "primary": pri, "secondary": sec,
                                        "picked_powersets": picked}
            return e
        a = entry("a", "Class_Brute", "SS", "Inv")
        self.assertIsNone(bc.compare([a])["scope"])
        self.assertEqual(bc.compare([a, entry("b", "Class_Brute", "SS", "Inv")])["scope"],
                         "same_powersets")
        self.assertEqual(bc.compare([a, entry("b", "Class_Brute", "SS", "WP")])["scope"],
                         "same_archetype")
        cross = bc.compare([a, entry("b", "Class_Tanker", "Inv", "SS")])
        self.assertEqual(cross["scope"], "cross_archetype")
        self.assertIn("all-archetype", cross["scope_note"])
        refused = {"label": "x", "evaluation": None, "error": "no"}
        self.assertIsNone(bc.compare([a, refused])["scope"])   # one evaluated build: no scope
        # a refused column is named in the scope, never silently left out of it
        mixed = bc.compare([a, entry("b", "Class_Brute", "SS", "Inv"), refused])
        self.assertEqual(mixed["scope"], "same_powersets")
        self.assertIn("1 could not be evaluated", mixed["scope_note"])
        # the PICKS decide, not how the request spelled the powersets
        sets = ["Brute_Defense.Invulnerability", "Brute_Melee.Super_Strength"]
        spelled = bc.compare([entry("a", "Class_Brute", "Brute_Melee.Super_Strength", None, sets),
                              entry("b", "Class_Brute", "Super Strength", "Invuln", sets)])
        self.assertEqual(spelled["scope"], "same_powersets")
        other = bc.compare([entry("a", "Class_Brute", "SS", "Inv", sets),
                            entry("b", "Class_Brute", "SS", "Inv",
                                  ["Brute_Defense.Willpower", "Brute_Melee.Super_Strength"])])
        self.assertEqual(other["scope"], "same_archetype")

    def test_no_overall_winner_is_declared(self):
        result = bc.compare([stub("a", {"defense": ("S", 45.0)}), stub("b", {"recharge": ("S", 90.0)})])
        self.assertFalse({"winner", "overall", "total", "score"} & set(result))
        self.assertTrue(any("No overall winner" in n for n in result["notes"]))


class IdentityTests(unittest.TestCase):
    """Which character is rated (owner, 2026-11-14): archetype, primary,
    secondary, pools and epic, by the names the player sees."""

    def test_identity_from_the_picks(self):
        import build_evaluation as be
        powers = [{"full_name": f} for f in (
            "Blaster_Ranged.Fire_Blast.Flares", "Blaster_Support.Radiation_Manipulation.Electron_Shackles",
            "Pool.Invisibility.Stealth", "Pool.Speed.Hasten", "Pool.Speed.Super_Speed",
            "Epic.Blaster_Mace_Mastery.Body_Armor", "Inherent.Inherent.Sprint")]
        ident = be._identity({"archetype": "Class_Blaster"}, powers, {"display_name": "Blaster"})
        self.assertEqual(ident["archetype"], "Blaster")
        self.assertEqual(ident["primary"]["display_name"], "Fire Blast")          # inferred from the picks
        self.assertEqual(ident["secondary"]["display_name"], "Atomic Manipulation")  # never the internal name
        self.assertEqual([p["display_name"] for p in ident["pools"]], ["Concealment", "Speed"])
        self.assertEqual(ident["epic"]["display_name"], "Mace Mastery")
        bare = be._identity({"archetype": "Class_Blaster"}, powers[:2], {"display_name": "Blaster"})
        self.assertEqual((bare["pools"], bare["epic"]), ([], None))

    def test_veat_names_base_set_and_branch(self):
        import build_evaluation as be
        powers = [{"full_name": "Arachnos_Soldiers.Arachnos_Soldier.Single_Shot"},
                  {"full_name": "Arachnos_Soldiers.Crab_Spider_Soldier.Channelgun"},
                  {"full_name": "Training_Gadgets.Crab_Spider_Training.Crab_Spider_Armor_Upgrade"}]
        ident = be._identity({"archetype": "Class_Arachnos_Soldier"}, powers, {"display_name": "Arachnos Soldier"})
        self.assertEqual(ident["primary"]["full_name"], "Arachnos_Soldiers.Arachnos_Soldier")
        self.assertEqual([p["full_name"] for p in ident["primary_also"]],
                         ["Arachnos_Soldiers.Crab_Spider_Soldier"])          # the branch is named too
        named = be._identity({"archetype": "Class_Arachnos_Soldier",
                              "primary": "Arachnos_Soldiers.Crab_Spider_Soldier"}, powers, {})
        self.assertEqual(named["primary"]["full_name"], "Arachnos_Soldiers.Crab_Spider_Soldier")  # request first

    def test_injected_catalogue_is_used(self):
        import build_evaluation as be
        cat = {"pools": [], "by_archetype": {"Class_Blaster": {"primary": [
            {"full_name": "Blaster_Ranged.Fire_Blast", "display_name": "Injected Fire"}]}}}
        ident = be._identity({"archetype": "Class_Blaster"}, [{"full_name": "Blaster_Ranged.Fire_Blast.Flares"}],
                             {}, powersets=cat)
        self.assertEqual(ident["primary"]["display_name"], "Injected Fire")

    def test_picked_sets_is_the_one_derivation(self):
        import build_evaluation as be
        powers = [{"full_name": f} for f in ("B.Y.p", "Pool.Speed.Hasten", "A.X.q", "B.Y.r", "Epic.E.s")]
        self.assertEqual(be._picked_sets(powers), ["B.Y", "Pool.Speed", "A.X", "Epic.E"])
        self.assertEqual(be._picked_powersets(powers), ["A.X", "B.Y"])


class CompareRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        cls.srv = srv
        cls.client = srv.app.test_client()
        cls.brute = cls.generate("Class_Brute", "Brute_Melee.Super_Strength", "Brute_Defense.Invulnerability")
        cls.ff = cls.generate("Class_Defender", "Defender_Buff.Force_Field", "Defender_Ranged.Energy_Blast")

    @classmethod
    def generate(cls, at, pri, sec):
        ap = cls.client.post("/build/autopick", json={
            "archetype": at, "primary": pri, "secondary": sec, "content": "general"}).get_json()
        solved = cls.client.post("/build/solve", json={
            "archetype": at, "content": "general", "tier": "premium", "preserve": False,
            "powers": ap["powers"]}).get_json()
        return {"archetype": at, "primary": pri, "secondary": sec, "powers": solved["powers"]}

    def post(self, entries):
        return self.client.post("/build/compare", json={"builds": entries})

    def test_scorecard_and_comparison_through_the_route(self):
        one = self.post([{"label": "Brute", "build": self.brute}]).get_json()
        self.assertEqual((one["ok"], one["mode"]), (True, "scorecard"))
        self.assertTrue(one["columns"][0]["rated"])
        two = self.post([{"label": "Brute", "build": self.brute},
                         {"label": "FF", "build": self.ff}]).get_json()
        self.assertEqual(two["mode"], "comparison")
        self.assertEqual(len(two["rows"]), 38)
        self.assertTrue(any(r["meaningful"] for r in two["rows"]))

    def test_refusals_come_back_as_columns(self):
        res = self.post([{"label": "Brute", "build": self.brute},
                         {"label": "PvP", "build": dict(self.brute, pvp=True)}])
        self.assertEqual(res.status_code, 200)
        col = res.get_json()["columns"][1]
        self.assertFalse(col["ok"])
        self.assertIn("PvP", col["error"])

    def test_bad_requests(self):
        for entries in ([], [{"label": "x", "build": self.brute}] * 5, [{"label": "x"}], "nope"):
            with self.subTest(entries=str(entries)[:30]):
                self.assertEqual(self.post(entries).status_code, 400)

    def test_read_only(self):
        saves = Path(self.srv._saves_dir())
        before = sorted(p.name for p in saves.glob("*")) if saves.exists() else []
        posted = copy.deepcopy(self.brute)
        self.post([{"label": "Brute", "build": posted}])
        after = sorted(p.name for p in saves.glob("*")) if saves.exists() else []
        self.assertEqual(before, after)
        self.assertEqual(posted, self.brute)


if __name__ == "__main__":
    unittest.main()
