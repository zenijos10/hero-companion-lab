"""Battery for the max strike (server/strike.py).

    python tools/test_strike.py

The chain rule (biggest ready hit, refired on recharge, inside the window), the
buff-click rule (a damage-buff click that deals no damage itself; never an
attack's own Defiance row, never Power Boost), and the real route: a generated
Fire/Fire Blaster's strike beats its sustained damage over the same seconds,
and the same build with its buff clicks removed (the negative control) strikes
lower and names no buff.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "server")]

import build_ratings  # noqa: E402
import engine  # noqa: E402
import strike  # noqa: E402


def attack(name, damage, cast, recharge, aoe=False):
    return {"name": name, "full_name": "X." + name, "damage": damage, "cast_time": cast,
            "recharge": recharge, "is_aoe": aoe, "dpa": damage / cast}


class ChainTests(unittest.TestCase):
    def test_best_order_not_biggest_first(self):
        # biggest-first: Big 0-2, Small 2-3, 4-5, Big 6-8, Small 8-9 = 900;
        # the best order opens with Small and fits a fourth Small: 1000
        big, small = attack("Big", 300, 2.0, 4.0), attack("Small", 100, 1.0, 1.0)
        picked, used, exact = strike.chain([small, big], 10.0)
        self.assertTrue(exact)
        self.assertEqual(sum(a["damage"] for a in picked), 1000)
        self.assertEqual([a["name"] for a in picked].count("Big"), 2)
        self.assertLessEqual(used, 10.0)

    def test_more_attacks_never_strike_lower(self):
        pool = [attack("A", 260, 2.67, 8.0), attack("B", 150, 1.17, 4.0),
                attack("C", 120, 1.0, 2.0), attack("D", 400, 3.3, 20.0)]
        for k in range(1, len(pool)):
            fewer = sum(a["damage"] for a in strike.chain(pool[:k], 10.0)[0])
            more = sum(a["damage"] for a in strike.chain(pool[:k + 1], 10.0)[0])
            self.assertGreaterEqual(more, fewer)

    def test_waits_when_nothing_is_ready_and_never_overruns(self):
        only = attack("Only", 100, 3.0, 5.0)              # 0-3, ready at 8, 8-11 overruns
        picked, used, exact = strike.chain([only], 10.0)
        self.assertEqual(len(picked), 1)
        self.assertEqual(used, 3.0)
        self.assertEqual(strike.chain([attack("Long", 50, 12.0, 0.0)], 10.0)[0], [])


class BuffClickTests(unittest.TestCase):
    def test_which_clicks_are_fired(self):
        buff = {"power_type": 0, "self_effects": [
            {"mode": True, "effect": "DamageBuff", "scale": 8.0, "duration": 10.0}]}
        self.assertEqual(strike._buff_duration(buff), 10.0)
        defiance = dict(buff, damage_effects=[{"damage_type": "Fire"}])
        self.assertEqual(strike._buff_duration(defiance), 0.0)   # an attack's own row is Defiance
        crash = {"power_type": 0, "self_effects": [
            {"mode": True, "effect": "DamageBuff", "scale": -999, "duration": 10.0, "delay": 10}]}
        self.assertEqual(strike._buff_duration(crash), 0.0)     # Rage's crash is not a buff
        toggle = dict(buff, power_type=2)
        self.assertEqual(strike._buff_duration(toggle), 0.0)    # a toggle is already counted

    def test_real_records(self):
        import json
        with open(os.path.join(ROOT, "data", "powers.json"), encoding="utf-8") as f:
            sets = json.load(f)
        rec = {r["full_name"]: r for r in sets["Blaster_Support.Energy_Manipulation"]}
        self.assertEqual(strike._buff_duration(rec["Blaster_Support.Energy_Manipulation.Build_Up"]), 10.0)
        self.assertEqual(strike._buff_duration(rec["Blaster_Support.Energy_Manipulation.Power_Boost"]), 0.0)
        water = {r["full_name"]: r for r in sets["Blaster_Ranged.Water_Blast"]}
        self.assertGreater(strike._buff_duration(water["Blaster_Ranged.Water_Blast.Tidal_Forces"]), 0.0)
        self.assertEqual(strike._buff_duration(water["Blaster_Ranged.Water_Blast.Whirlpool"]), 0.0)

    def test_census_buffs_versus_defiance_rows(self):
        # every click whose damage-buff row is real: 157 on archetype buff tables;
        # 7 more carry Defiance's flat per-cast row on a *_Ones table and are not buffs
        import json
        with open(os.path.join(ROOT, "data", "powers.json"), encoding="utf-8") as f:
            sets = json.load(f)
        recs = [r for pw in sets.values() for r in pw]
        buffs = [r for r in recs if strike._buff_duration(r) > 0]
        self.assertEqual(len(buffs), 157)
        lookalike = [r for r in recs if (r.get("power_type") or 0) == 0 and not r.get("damage_effects")
                     and strike._buff_duration(r) == 0
                     and any(fx.get("mode") and fx.get("effect") == "DamageBuff"
                             and (fx.get("scale") or 0) > 0 and not fx.get("delay")
                             for fx in r.get("self_effects") or [])]
        self.assertEqual(len(lookalike), 7)


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        cls.c = srv.app.test_client()
        at, pri, sec = "Class_Blaster", "Blaster_Ranged.Fire_Blast", "Blaster_Support.Fire_Manipulation"
        ap = cls.c.post("/build/autopick", json={"archetype": at, "primary": pri, "secondary": sec,
                                                 "content": "general"}).get_json()
        sol = cls.c.post("/build/solve", json={"archetype": at, "primary": pri, "secondary": sec,
                                               "content": "general", "tier": "premium",
                                               "preserve": False, "powers": ap["powers"]}).get_json()
        cls.build = {"archetype": at, "primary": pri, "secondary": sec, "powers": sol["powers"]}
        cls.ev = cls.c.post("/build/evaluate", json={"build": cls.build}).get_json()

    def test_strike_beats_sustained_with_buffs(self):
        s = self.ev["measurements"]["offense"]["max_strike"]
        self.assertTrue(s["buffs"], "the generated Fire/Fire Blaster carries Build Up or Aim")
        self.assertEqual(s["window_seconds"], strike.STRIKE_SECONDS)   # a burst, never a long buff's length
        st = s["single_target"]
        self.assertTrue(st["exact"] and s["aoe_per_target"]["exact"])
        self.assertGreater(st["vs_sustained"], 1.0)
        self.assertLessEqual(st["seconds_used"], s["window_seconds"])
        by = st["by_position"]
        self.assertGreaterEqual(by["melee"]["damage"], by["midrange"]["damage"])
        self.assertGreaterEqual(by["midrange"]["damage"], by["range"]["damage"])
        aoe = s["aoe_per_target"]
        self.assertLessEqual(aoe["damage"], st["damage"])        # area attacks are a subset

    def test_negative_control_without_buff_clicks(self):
        import server as srv
        keep = [p for p in self.build["powers"]
                if strike._buff_duration(srv.POWER_BY_FULL.get(p["full_name"]) or {}) == 0]
        self.assertLess(len(keep), len(self.build["powers"]))
        ev = self.c.post("/build/evaluate", json={"build": dict(self.build, powers=keep)}).get_json()
        s = ev["measurements"]["offense"]["max_strike"]
        self.assertEqual(s["buffs"], [])
        self.assertEqual(s["window_seconds"], strike.STRIKE_SECONDS)
        full = self.ev["measurements"]["offense"]["max_strike"]["single_target"]["damage"]
        self.assertLess(s["single_target"]["damage"], full)

    def test_graded_beside_sustained_with_its_reason(self):
        cats = self.ev["ratings"]["categories"]
        for key in ("strike_single_target", "strike_aoe"):
            self.assertEqual(build_ratings.SECTIONS[key], "Damage")
            self.assertIn(key, cats)
            self.assertIn("10 s", cats[key].get("detail") or "")

    def test_momentum_gated_attacks_cannot_open(self):
        gated = next(iter(engine.MOMENTUM_GATED_DISPLAY))
        records = {"X." + gated: {}, "X.Open": {}}
        self.assertFalse(strike._usable(attack(gated, 500, 2.0, 5.0), records))
        self.assertTrue(strike._usable(attack("Open", 100, 1.0, 5.0), records))


if __name__ == "__main__":
    unittest.main()
