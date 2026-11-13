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
        far = {"melee": 0.25, "midrange": 0.0, "range": 0.75}
        self.assertEqual(rp.blend({"damage": prof, "control": None, "support": far}),
                         {"melee": 0.5, "midrange": 0.0, "range": 0.5})
        # damage weighs double control or support (owner: distance matters most there)
        self.assertEqual(rp.blend({"damage": prof, "support": far}, rp.OVERALL_WEIGHTS),
                         {"melee": 0.583, "midrange": 0.0, "range": 0.417})

    def test_melee_reach_follows_the_owners_rules(self):
        """Melee critters follow you: range alone barely helps; keeping them at
        bay (root/knock/repel) or slowing their approach does."""
        far = {"melee": 0.0, "midrange": 0.0, "range": 1.0}
        close = {"melee": 1.0, "midrange": 0.0, "range": 0.0}
        self.assertEqual(surv.melee_reach(close, keep_at_bay=1.0)["reach"], 1.0)   # up close: always
        running = surv.melee_reach(far)
        self.assertGreater(running["reach"], 0.9)          # they close the 60 ft in about 2 s
        self.assertAlmostEqual(running["approach_seconds"], 60.0 / 30.8, places=2)
        self.assertEqual(surv.melee_reach(far, keep_at_bay=1.0)["reach"], 0.0)
        slowed = surv.melee_reach(far, slow=0.5)
        self.assertLess(slowed["reach"], running["reach"])
        self.assertEqual(surv.melee_reach(far, slow=5.0)["approach_seconds"],
                         surv.melee_reach(far, slow=0.9)["approach_seconds"])      # slow cap
        self.assertEqual(surv.position_weights(0.5),
                         {"Melee": 0.5 / 3, "Ranged": 1 / 3, "AoE": 1 / 3})

    def test_keeping_them_at_bay_moves_toughness(self):
        t = totals({"Ranged": 40, "AoE": 40})
        far = {"melee": 0, "midrange": 0, "range": 1.0}
        running = surv.profile(t, inputs(), SC, 1200.0, 30.0, far)
        rooted = surv.profile(t, inputs(), SC, 1200.0, 30.0, far, keep_at_bay=1.0)
        close = surv.profile(t, inputs(), SC, 1200.0, 30.0, {"melee": 1.0, "midrange": 0, "range": 0},
                             keep_at_bay=1.0)
        self.assertGreater(rooted["toughness"], running["toughness"])
        self.assertLess(close["toughness"], rooted["toughness"])    # a root does not help up close
        self.assertEqual(rooted["melee_reach"]["keep_at_bay"], 1.0)

    def test_positioning_reads_area_roots_and_knocks(self):
        ledger = {"powers": [
            {"power": "Root", "area": "aoe", "cost": {"basis": "click cast on cooldown"},
             "controls": [{"mez": "Immobilized", "uptime": 0.6, "cycle_seconds": 10.0}]},
            {"power": "Knock", "area": "aoe", "cost": {"basis": "click cast on cooldown"},
             "controls": [{"mez": "Knockback", "uptime": 1.0, "duration_seconds": 9.0,
                           "cycle_seconds": 4.0}]},
            {"power": "Hold", "area": "aoe", "cost": {"basis": "toggle/auto: endurance"},
             "controls": [{"mez": "Held", "uptime": 1.0}]},
            {"power": "SingleRoot", "area": "single_target", "cost": {"basis": "toggle/auto"},
             "controls": [{"mez": "Immobilized", "uptime": 1.0}]}]}
        out = rm.positioning(ledger)
        self.assertEqual(out["keep_at_bay"], 0.75)           # a knock buys 3 s of every 4
        self.assertEqual(out["source"]["power"], "Knock")
        repel = {"powers": [{"power": "Repel", "area": "aoe", "cost": {"basis": "toggle/auto"},
                             "controls": [{"mez": "Repel", "uptime": 1.0}]}]}
        self.assertEqual(rm.positioning(repel)["keep_at_bay"], 1.0)
        self.assertEqual(rm.positioning({"powers": []})["keep_at_bay"], 0.0)


    def test_a_root_holds_only_the_ranks_it_beats(self):
        root = lambda held: {"powers": [{"power": "Root", "area": "aoe",  # noqa: E731
                                          "cost": {"basis": "toggle/auto"},
                                          "controls": [{"mez": "Immobilized", "uptime": 1.0,
                                                        "affects_in_one_application": held}]}]}
        self.assertEqual(rm.positioning(root(["minion"]))["keep_at_bay"], 0.6)
        self.assertEqual(rm.positioning(root(["minion", "lieutenant", "boss"]))["keep_at_bay"], 1.0)
        self.assertEqual(rm.positioning(root([]))["keep_at_bay"], 0.0)

    def test_a_self_centred_click_does_not_keep_them_away(self):
        clap = {"powers": [{"power": "P.Clap", "area": "aoe", "cost": {"basis": "click cast on cooldown"},
                            "controls": [{"mez": "Knockback", "cycle_seconds": 6.0}]}]}
        records = {"P.Clap": {"range": 0.0, "radius": 15.0}}
        self.assertEqual(rm.positioning(clap, records)["keep_at_bay"], 0.0)
        aimed = {"P.Clap": {"range": 80.0, "radius": 15.0}}
        self.assertEqual(rm.positioning(clap, aimed)["keep_at_bay"], 0.5)
        aura = {"powers": [dict(clap["powers"][0], cost={"basis": "toggle/auto"},
                                controls=[{"mez": "Repel", "cycle_seconds": None}])]}
        self.assertEqual(rm.positioning(aura, records)["keep_at_bay"], 1.0)   # an aura pushes them out


class CascadeTests(unittest.TestCase):
    def test_fixed_point_finishes_a_slow_climb(self):
        # slope 0.9999: 500 climb steps reach ~5% of the way; bisection finishes
        mean_hit = lambda d: 0.001 + 0.9999 * min(d, 50.0)  # noqa: E731
        d = surv.fixed_point(1.0, 0.0, mean_hit)
        self.assertAlmostEqual(d, 10.0, places=4)

    def test_cascade_hit_chance_is_per_attack_that_reaches(self):
        t = {"defense": {}, "resistance": {}, "bonus_extras": {}}
        inputs = {"tohit_debuff": 0.0, "def_debuff_in": 0.0}
        sc = dict(build_evaluation.scenario_params("rating_plus4"))
        full = surv.cascade(t, inputs, sc, surv.position_weights(1.0))
        kept = surv.cascade(t, inputs, sc, surv.position_weights(0.1))
        self.assertAlmostEqual(full["hit_chance_before"], kept["hit_chance_before"], places=4)
        self.assertLess(kept["landed_def_debuff_hits_per_minute"],
                        full["landed_def_debuff_hits_per_minute"])

    def test_fixed_point_and_ddr(self):
        w = surv.position_weights(1.0)
        t = totals({"Melee": 30, "Ranged": 30, "AoE": 30})
        c = surv.cascade(t, inputs(), SC, w)
        k = SC["enemies"] * SC["def_debuff_pressure"]
        d = c["debuff"]
        self.assertAlmostEqual(d, k * surv._mean_hit(t, SC, 0.0, w, d), places=5)   # a fixed point
        self.assertGreater(c["hit_chance_after"], c["hit_chance_before"])          # it cascades
        resisted = surv.cascade(totals({"Melee": 30, "Ranged": 30, "AoE": 30}, ddr=60), inputs(), SC, w)
        self.assertLess(resisted["debuff"], d)
        self.assertAlmostEqual(resisted["steady_def_debuff_without_ddr"], round(d, 4), places=4)

    def test_lower_defense_cascades_harder_and_the_floor_always_hits(self):
        w = surv.position_weights(1.0)
        soft = surv.cascade(totals({"Melee": 45, "Ranged": 45, "AoE": 45}), inputs(), SC, w)
        low = surv.cascade(totals({"Melee": 25, "Ranged": 25, "AoE": 25}), inputs(), SC, w)
        self.assertGreater(low["debuff"], soft["debuff"])
        self.assertGreater(soft["debuff"], 0.0)                 # even at the softcap
        self.assertGreater(soft["hit_chance_floor"], 0.05)      # 5% x +4 accuracy
        self.assertGreater(soft["landed_def_debuff_hits_per_minute"], 0.0)

    def test_without_constants_the_flat_model_is_kept(self):
        flat = dict(fp.SCENARIOS["general"], shift=4)
        c = surv.cascade(totals(), dict(inputs(), def_debuff_in=0.03), flat, surv.position_weights(1.0))
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


class ReviewFixTests(unittest.TestCase):
    """The /code-review findings on the breakdown, each pinned."""

    def test_sections_are_contiguous_and_complete(self):
        self.assertEqual(set(br.SECTIONS), set(br.CATEGORIES))
        seen, last = [], None
        for key in br.CATEGORIES:
            if br.SECTIONS[key] != last:
                self.assertNotIn(br.SECTIONS[key], seen, f"{key} reopens a section")
                seen.append(br.SECTIONS[key])
                last = br.SECTIONS[key]
        self.assertEqual(br.SECTIONS["buff_damage"], "Team buffs")
        self.assertEqual(br.SECTIONS[br.SUPPORT_INDEX], "Support")

    def test_patch_damage_is_unread_not_dropped(self):
        ig = "Brute_Melee.Radiation_Melee.Irradiated_Ground"
        patch = {"full_name": ig, "damage": 30.0, "damage_types": [], "is_aoe": True,
                 "chain_casts": 0, "cast_time": 0.0, "recharge": 1.0}
        punch = {"full_name": "Brute_Melee.Super_Strength.Haymaker", "damage": 100.0,
                 "damage_types": ["Smashing"], "is_aoe": False, "chain_casts": 10}
        out = rm.damage({"attacks": [patch, punch]}, BY_FULL)
        types = {t["type"]: t["damage_share"] for t in out["types"]}
        self.assertIn(rm.UNREAD, types)                       # 120 uses x 30 = 3600 of 4600
        self.assertLess(types["Smashing"], 0.5)
        self.assertEqual(out["profiles"]["aoe_damage"]["midrange"], 1.0)   # its patch's radius

    def test_untyped_rows_never_rank(self):
        split = rm._type_split({"damage_effects": [
            {"damage_type": "Special", "scale": 1.0}, {"damage_type": "Fire", "scale": 1.0}]}, {})
        self.assertEqual(split, {"Fire": 1.0})
        self.assertEqual(rm._type_split(None, {"damage_types": ["Special", "Cold"]}), {"Cold": 1.0})

    def test_self_crash_rows_are_not_a_debuff_offer(self):
        sets = rm._census(BY_FULL)["debuff"]
        crash = BY_FULL["Sentinel_Ranged.Electrical_Blast.Zapping_Bolt"]
        foe_rows = [e for e in crash["debuff_effects"]
                    if e.get("effect") == "Endurance" and e.get("target") != "Self"]
        if not foe_rows:
            self.assertNotIn(crash["powerset_full_name"], sets.get("Endurance", set()))

    def test_area_rule_is_the_engines(self):
        rec = {"range": 10.0, "radius": 0.0, "effect_area": 8}
        self.assertEqual(rp.band(rec), "melee" if not __import__("engine").is_aoe(rec) else "midrange")
        self.assertEqual(rp.band({"range": 10.0, "radius": 0.0, "effect_area": 2}), "midrange")

    def test_drains_are_area_only_and_profiled_apart(self):
        ledger = {"powers": [
            {"power": "A", "area": "single_target",
             "debuffs": [{"effect": "Endurance", "instant": True, "landing_per_second_vs_scenario": 5.0}]},
            {"power": "B", "area": "aoe",
             "debuffs": [{"effect": "Endurance", "instant": True, "landing_per_second_vs_scenario": 2.0},
                         {"effect": "Endurance", "instant": False, "uptime": 1.0,
                          "landing_peak_percent": {"vs_av": 1.0, "vs_scenario": 3.0}}]}]}
        out = rm.support_types(ledger, {})
        self.assertEqual(out["drains_per_second_percent"], {"Endurance": 2.0})
        self.assertEqual(out["debuffs_vs_spawn_percent"], {"Endurance": 3.0})
        self.assertEqual(br._RANGE_KEY["debuff_endurance_spawn"], "drain:Endurance")
        self.assertEqual(br._RANGE_KEY["debuff_resistance_av"], "debuff_av:Resistance")
        self.assertEqual(br._RANGE_KEY["debuff_defense_spawn"], "debuff_spawn:Defense")

    def test_drain_rate_counts_its_chance_once(self):
        """The peak is already chance-weighted, so the rate must not weigh it again."""
        import support_ledger
        import server as srv
        ctx = srv._stat_ctx("Class_Defender")
        rec = dict(BY_FULL["Defender_Ranged.Electrical_Blast.Short_Circuit"])
        sure = support_ledger.power_ledger({"full_name": rec["full_name"], "slots": []},
                                           dict(ctx, power_by_full={rec["full_name"]: rec}),
                                           0.0, SC, 1.0)
        rows = [dict(d, probability=0.25) if d.get("effect") == "Endurance" else d
                for d in rec["debuff_effects"]]
        rec2 = dict(rec, debuff_effects=rows)
        quarter = support_ledger.power_ledger({"full_name": rec["full_name"], "slots": []},
                                              dict(ctx, power_by_full={rec["full_name"]: rec2}),
                                              0.0, SC, 1.0)
        rate = lambda e: next(d["landing_per_second_vs_scenario"] for d in e["debuffs"]  # noqa: E731
                              if d["effect"] == "Endurance")
        self.assertAlmostEqual(rate(quarter), rate(sure) * 0.25, places=2)

    def test_cascade_detail_names_the_scenarios_shift(self):
        ev = {"scenario": {"enemy_level_shift": 3},
              "measurements": {"survival": {"defense_cascade": {
                  "model": "cascade", "hit_chance_floor": 0.07, "steady_def_debuff": 0.02,
                  "steady_def_debuff_without_ddr": 0.02, "hit_chance_before": 0.07,
                  "hit_chance_after": 0.08}}}}
        self.assertTrue(br._cascade_detail(ev).startswith("+3 enemies"))


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
