"""Battery for the rating breakdown (owner, 2026-11-11): where a build operates
(server/range_profile.py), damage types by how often they fire, control split
single target vs area, every buff and debuff type with its rarity, debuff
resistance and the defense cascade (server/rating_measures.py,
server/survival_profile.py), and the rarity-weighted support index.

Run: python tools/test_rating_breakdown.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-breakdown-"))

import build_evaluation  # noqa: E402
import build_ratings as br  # noqa: E402
import first_principles as fp  # noqa: E402
import range_profile as rp  # noqa: E402
import rating_measures as rm  # noqa: E402
import survival_profile as surv  # noqa: E402

POWERS = json.loads((ROOT / "data" / "powers.json").read_text(encoding="utf-8"))
BY_FULL = {p["full_name"]: p for lst in POWERS.values() for p in lst}
SC = build_evaluation.scenario_params("rating_plus4")


def totals(defense=None, resistance=None, ddr=0.0):
    row = lambda rows: {k: {"value": v} for k, v in (rows or {}).items()}  # noqa: E731
    return {"defense": row(defense), "resistance": row(resistance),
            "bonus_extras": {"def_debuff_resist": {"value": ddr}}}


def inputs(tohit=0.0):
    return {"hp": 1200.0, "regen_hps": 5.0, "self_heal_hps": 0.0, "absorb_hps": 0.0,
            "tohit_debuff": tohit, "def_debuff_in": 0.0}


class RangeTests(unittest.TestCase):
    def test_bands_follow_the_power_geometry(self):
        cases = {"Brute_Melee.Super_Strength.Haymaker": "melee",
                 "Brute_Melee.Super_Strength.Foot_Stomp": "midrange",    # around you
                 "Blaster_Ranged.Fire_Blast.Blaze": "range",
                 "Blaster_Ranged.Fire_Blast.Fire_Ball": "range",
                 "Blaster_Ranged.Fire_Blast.Fire_Breath": "range"}       # a 40 ft cone
        for name, want in cases.items():
            self.assertEqual(rp.band(BY_FULL[name]), want, name)
        self.assertIsNone(rp.band({"range": 0, "radius": 0, "effect_area": 1}))   # self only
        self.assertEqual(rp.band({"range": 20, "radius": 0, "effect_area": 3}), "midrange")
        print(f"{len(cases)} of {len(cases)} expected real powers banded")

    def test_profile_shares(self):
        recs = [(BY_FULL["Brute_Melee.Super_Strength.Haymaker"], 3.0),
                (BY_FULL["Blaster_Ranged.Fire_Blast.Blaze"], 1.0)]
        prof = rp.profile(recs)
        self.assertEqual(prof, {"melee": 0.75, "midrange": 0.0, "range": 0.25})
        self.assertIsNone(rp.profile([({"range": 0}, 5.0)]))
        self.assertEqual(rp.describe(prof), "75% melee, 25% range")
        self.assertEqual(rp.blend([prof, None, {"melee": 0.25, "midrange": 0.0, "range": 0.75}]),
                         {"melee": 0.5, "midrange": 0.0, "range": 0.5})

    def test_operating_range_moves_toughness(self):
        weights = surv.position_weights({"melee": 0.0, "midrange": 0.0, "range": 1.0})
        self.assertEqual(weights["Melee"], 0.0)
        # a build with only Ranged defense is tougher where melee attacks cannot reach it
        t = totals({"Ranged": 40, "AoE": 40})
        close = surv.profile(t, inputs(), SC, 1200.0, 30.0, {"melee": 1.0, "midrange": 0, "range": 0})
        far = surv.profile(t, inputs(), SC, 1200.0, 30.0, {"melee": 0, "midrange": 0, "range": 1.0})
        self.assertGreater(far["toughness"], close["toughness"])
        self.assertEqual(far["toughness"], far["at_range"])


class CascadeTests(unittest.TestCase):
    def test_fixed_point_and_ddr(self):
        w = surv.position_weights(None)
        t = totals({"Melee": 30, "Ranged": 30, "AoE": 30})
        c = surv.cascade(t, inputs(), SC, w)
        k = SC["enemies"] * SC["enemy_attacks_per_second"] * SC["def_debuff_attack_share"] \
            * SC["def_debuff_per_hit"] * SC["def_debuff_seconds"]
        d = c["debuff"]
        self.assertAlmostEqual(d, k * surv._mean_hit(t, SC, 0.0, w, d), places=5)   # a fixed point
        self.assertGreater(c["hit_chance_after"], c["hit_chance_before"])          # it cascades
        resisted = surv.cascade(totals({"Melee": 30, "Ranged": 30, "AoE": 30}, ddr=60), inputs(), SC, w)
        self.assertLess(resisted["debuff"], d)
        self.assertAlmostEqual(resisted["steady_def_debuff_without_ddr"], round(d, 4), places=4)

    def test_lower_defense_cascades_harder_and_the_floor_always_hits(self):
        w = surv.position_weights(None)
        soft = surv.cascade(totals({"Melee": 45, "Ranged": 45, "AoE": 45}), inputs(), SC, w)
        low = surv.cascade(totals({"Melee": 25, "Ranged": 25, "AoE": 25}), inputs(), SC, w)
        self.assertGreater(low["debuff"], soft["debuff"])
        self.assertGreater(soft["debuff"], 0.0)                 # even at the softcap
        self.assertGreater(soft["hit_chance_floor"], 0.05)      # 5% x +4 accuracy
        self.assertGreater(soft["landed_def_debuff_hits_per_minute"], 0.0)

    def test_without_constants_the_flat_model_is_kept(self):
        flat = dict(fp.SCENARIOS["general"], shift=4)
        c = surv.cascade(totals(), dict(inputs(), def_debuff_in=0.03), flat, surv.position_weights(None))
        self.assertEqual(c["model"], "flat")
        self.assertEqual(c["debuff"], 0.03)


class TypeTests(unittest.TestCase):
    def test_rarity_comes_from_the_data(self):
        r = rm.rarity(BY_FULL)
        self.assertEqual(r["debuff"]["Slow"]["weight"], 1.0)           # the commonest
        self.assertGreater(r["debuff"]["HitPoints"]["weight"], 5.0)    # 4 powersets
        self.assertGreater(r["debuff"]["Regeneration"]["weight"], r["debuff"]["Resistance"]["weight"])
        self.assertGreater(r["buff"]["Regeneration"]["weight"], r["buff"]["Defense"]["weight"])
        print(f"{len(r['buff'])} buff types and {len(r['debuff'])} debuff types censused")

    def test_type_split_and_description(self):
        split = rm._type_split(BY_FULL["Blaster_Ranged.Fire_Blast.Blaze"], {})
        self.assertEqual(set(split), {"Fire"})
        self.assertEqual(rm.describe_types([{"type": "Fire", "damage_share": 0.72},
                                            {"type": "Cold", "damage_share": 0.28}]),
                         "mostly Fire (72%), then Cold (28%)")

    def test_support_index(self):
        cuts = {"debuff_hitpoints_av": {"cuts": {"B": 10.0}}, "buff_defense": {"cuts": {"B": 5.0}}}
        rarity = {"debuff": {"HitPoints": {"weight": 5.0}}, "buff": {"Defense": {"weight": 1.0}}}
        self.assertEqual(br.support_index({"debuff_hitpoints_av": 10.0, "buff_defense": 10.0},
                                          cuts, rarity), 7.0)      # 5x1 + 1x2
        self.assertEqual(br.support_index({}, cuts, rarity), 0.0)
        self.assertIsNone(br.support_index({}, cuts, None))


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        cls.c = srv.app.test_client()

    def build(self, at, pri, sec):
        ap = self.c.post("/build/autopick", json={"archetype": at, "primary": pri,
                                                  "secondary": sec, "content": "general"}).get_json()
        sol = self.c.post("/build/solve", json={"archetype": at, "primary": pri, "secondary": sec,
                                                "content": "general", "tier": "premium",
                                                "preserve": False, "powers": ap["powers"]}).get_json()
        return {"archetype": at, "primary": pri, "secondary": sec, "powers": sol["powers"]}

    def evaluate(self, b):
        return self.c.post("/build/evaluate", json={"build": b}).get_json()

    def test_corruptor_breakdown(self):
        ev = self.evaluate(self.build("Class_Corruptor", "Corruptor_Ranged.Fire_Blast",
                                      "Corruptor_Buff.Radiation_Emission"))
        m = ev["measurements"]
        self.assertEqual(m["offense"]["damage_types"][0]["type"], "Fire")
        sup = m["support"]
        self.assertAlmostEqual(sup["control_single_target"]["value"] + sup["control_aoe"]["value"],
                               sup["control_proxy"]["value"], delta=0.2)
        # an area -Resistance toggle lands on the AV too
        old_av = sup["team_support"]["summary"]["debuffs_landing_average_percent"]["single_target_vs_av"]
        self.assertGreater(sup["support_by_type"]["debuffs_vs_av_percent"]["Resistance"],
                           old_av.get("Resistance", 0.0))
        prof = ev["range_profile"]["profiles"]
        self.assertGreater(prof["single_target_damage"]["range"], 0.9)
        cats = ev["ratings"]["categories"]
        self.assertEqual(set(cats), set(br.CATEGORIES))
        self.assertIn("mostly Fire", cats["single_target_damage"]["detail"])
        self.assertTrue(cats["single_target_damage"]["where"])
        for key, row in cats.items():
            if row["grade"] in ("None", "N/A"):
                self.assertIsNone(row["where"], key)
        self.assertIn(cats[br.SUPPORT_INDEX]["grade"], tuple("SABCDF"))

    def test_melee_build_operates_up_close(self):
        ev = self.evaluate(self.build("Class_Brute", "Brute_Melee.Super_Strength",
                                      "Brute_Defense.Invulnerability"))
        overall = ev["range_profile"]["profiles"]["overall"]
        self.assertGreater(overall["melee"] + overall["midrange"], overall["range"])
        # its single-target control is mostly melee (Knockout Blow), with Hurl at range
        self.assertGreater(ev["range_profile"]["profiles"]["control_single_target"]["melee"], 0.5)
        dr = ev["measurements"]["survival"]["debuff_resistance"]
        self.assertEqual(set(dr["not_read"]), set(rm.NOT_READ))


if __name__ == "__main__":
    unittest.main()
