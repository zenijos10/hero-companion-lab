"""Battery for pulsing patch damage (engine.patch_damage, data/patch_pets.json).

    python tools/test_patch_pets.py

The owner's case (2026-11-15, "archery doesnt have data? Go get it!"): Rain of
Arrows and 55 more patch powers deal their damage through a pseudo-pet that
pulses with no animation, so the pet chain never priced them. Pins the pulse
count, Rain of Arrows' per-target damage from City of Data's lifetime and the
pet class's table, the coverage denominator against an independent census,
the redirect/entity table rule, and the real route with its negative control
(no Rain of Arrows: no row, and the pet channel never double counts it).
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "server"), os.path.join(ROOT, "tools")]

import engine  # noqa: E402
import fetch_patch_pets  # noqa: E402

ROA = "Blaster_Ranged.Archery.Rain_of_Arrows"


class PulseTests(unittest.TestCase):
    def test_pulse_count(self):
        self.assertEqual(engine.patch_pulses(1.0, 0.4), 3)      # 0, 0.4, 0.8
        self.assertEqual(engine.patch_pulses(0.0, 2.0), 1)      # lands once
        self.assertEqual(engine.patch_pulses(15.0, 1.0), 15)    # 0..14, never at 15
        self.assertEqual(engine.patch_pulses(5.0, 0.0), 1)


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "data", "patch_pets.json"), encoding="utf-8") as f:
            cls.data = json.load(f)
        with open(os.path.join(ROOT, "data", "powers.json"), encoding="utf-8") as f:
            cls.powers = json.load(f)
        with open(os.path.join(ROOT, "data", "powersets.json"), encoding="utf-8") as f:
            cls.powersets = json.load(f)

    def test_every_summoner_is_mapped_or_stated(self):
        expected = set(fetch_patch_pets.census(self.powers, self.powersets))
        mapped, stated = set(self.data["powers"]), set(self.data["missing"])
        print(f"{len(mapped)} of {len(expected)} expected patch summoners priced, "
              f"{len(stated)} stated")
        self.assertEqual(mapped | stated, expected)
        self.assertFalse(mapped & stated)
        self.assertEqual((len(mapped), len(stated)), (56, 9))
        self.assertTrue(all(self.data["missing"].values()))

    def test_rain_of_arrows_from_city_of_data(self):
        (ent,) = [e for e in self.data["powers"][ROA]["entities"] if e["pulse_powers"]]
        self.assertEqual((ent["lifetime"], ent["class"]), (1.0, "Class_Minion_Pets"))
        self.assertTrue(ent["copy_creator_mods"])


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        cls.srv = srv
        cls.c = srv.app.test_client()

    def test_rain_of_arrows_per_target(self):
        dmg, types, buffs, _recs = engine.patch_damage(ROA, self.srv._stat_ctx("Class_Blaster"))
        self.assertAlmostEqual(dmg, 3 * 1.35 * 55.61, delta=0.5)   # 3 pulses on the pet table
        self.assertEqual(types, {"Lethal"})
        self.assertTrue(buffs)
        self.assertIsNone(engine.patch_damage("Blaster_Ranged.Archery.Snap_Shot",
                                              self.srv._stat_ctx("Class_Blaster")))

    def test_redirect_runs_on_the_casters_tables(self):
        name = "Defender_Buff.Cold_Domination.Sleet"
        self.assertTrue(all(e["class"] is None for e in self.data_entities(name)))
        ctx = dict(self.srv._stat_ctx("Class_Defender"))
        here = engine.patch_damage(name, ctx)[0]
        ctx["at_column"] = self.srv.AT_COLUMN["Class_Minion_Pets"]
        self.assertNotAlmostEqual(engine.patch_damage(name, ctx)[0], here)

    def test_an_entity_that_copies_nothing_takes_no_caster_buff(self):
        (ent,) = self.data_entities("Blaster_Support.Gadgets.Caltrops")
        self.assertFalse(ent["copy_creator_mods"])
        self.assertFalse(engine.patch_damage("Blaster_Support.Gadgets.Caltrops",
                                             self.srv._stat_ctx("Class_Blaster"))[2])

    def data_entities(self, name):
        return engine.patch_pet_plan()[name]["entities"]

    def test_real_route_and_negative_control(self):
        at, pri, sec = "Class_Blaster", "Blaster_Ranged.Archery", "Blaster_Support.Tactical_Arrow"
        ap = self.c.post("/build/autopick", json={"archetype": at, "primary": pri, "secondary": sec,
                                                  "content": "general"}).get_json()
        base = {"archetype": at, "primary": pri, "secondary": sec,
                "powers": [p for p in ap["powers"] if p["full_name"] != ROA]}
        with_roa = dict(base, powers=base["powers"] + [
            {"full_name": ROA, "pick_level": 32, "slots": [{"piece_uid": None}]}])
        rows = {a["full_name"]: a for a in
                self.c.post("/build/calculate", json=with_roa).get_json()["offense"]["attacks"]}
        roa = rows[ROA]
        self.assertGreater(roa["damage"], 225)            # + the Blaster's global buffs, copied
        self.assertTrue(roa["is_aoe"])
        self.assertEqual(roa["cast_time"], 2.0)
        without = {a["full_name"] for a in
                   self.c.post("/build/calculate", json=base).get_json()["offense"]["attacks"]}
        self.assertNotIn(ROA, without)
        pets = [self.c.post("/build/evaluate", json={"build": b}).get_json()
                ["measurements"]["offense"]["scenario_pet_dps"]["value"] for b in (base, with_roa)]
        self.assertEqual(pets[0], pets[1])                 # the pet channel never prices it twice


if __name__ == "__main__":
    unittest.main()
