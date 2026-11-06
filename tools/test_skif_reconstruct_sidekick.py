"""Real Sidekick v5 fixture and real Homecoming datasets: conversion without guessing."""
import copy
import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
from sidekick_reconstruct import reconstruct_build
from preview_skif import _enhancement_lookups, main as preview_main


class RealSidekickReconstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkout = ROOT / "_sidekick_contract_fixture"
        cls.contract = cls.checkout / "contract/homecoming"
        fixture = cls.checkout / "fixtures/skif/v5/rb5d_browser_pass.skif"
        if not fixture.exists():
            raise AssertionError("Missing pinned Sidekick v5 integration fixture")
        cls.source = json.loads(fixture.read_text(encoding="utf-8"))
        powers = json.loads((ROOT / "data/powers.json").read_text(encoding="utf-8"))
        cls.hero = {p["full_name"]: p for group in powers.values() for p in group}
        cls.hero_sets = json.loads((ROOT / "data/powersets.json").read_text(encoding="utf-8"))
        cls.enhancements = _enhancement_lookups()
        cls.incarnates = json.loads((ROOT / "data/incarnates.json").read_text(encoding="utf-8"))

    @classmethod
    def reconstruct(cls, doc):
        return reconstruct_build(doc, cls.hero, cls.hero_sets, cls.contract,
                                 cls.enhancements, incarnate_catalog=cls.incarnates)

    def v5_from_v4(self, name, buckets=("primary", "secondary", "pools", "inherents")):
        """Sidekick's v4 sample in v5 shape: v5 drops each power's "name" and
        writes the archetype as its id; nothing else is changed."""
        old = json.loads((self.checkout / f"fixtures/skif/v4/{name}.skif")
                         .read_text(encoding="utf-8"))["build"]

        def slot(sl):
            # v4 called both the booster and the HO grade "boost"; v5 writes
            # an IO's as "booster" and a special's as "relativeLevel".
            if not sl or "boost" not in sl:
                return sl
            out = {k: v for k, v in sl.items() if k != "boost"}
            out["relativeLevel" if sl["type"] in ("special", "origin") else "booster"] = sl["boost"]
            return out

        def power(p):
            out = {k: v for k, v in p.items() if k in ("internalName", "level")}
            out["slots"] = [slot(sl) for sl in p["slots"]]
            return out

        def selection(sel):
            return {"id": sel["id"], "powers": [power(p) for p in sel["powers"]]}
        build = {"dataset": "homecoming", "archetype": old["archetype"]["id"],
                 "level": old["level"], "name": old.get("name") or name}
        for bucket in buckets:
            value = old.get(bucket)
            if bucket == "pools":
                build["pools"] = [selection(p) for p in value or []]
            elif bucket == "inherents":
                build["inherents"] = [power(p) for p in value or []]
            elif value:
                build[bucket] = selection(value)
        return {"version": 5, "build": build}

    # KNOWN GAP (follow-up): these sets' piece uids differ between Hero
    # Companion's Mids-derived catalog and the game's (Sidekick's) names, e.g.
    # our Crafted_Shrapnel_A is the game's Crafted_Artillery_A. Until bridged,
    # they refuse explicitly; the pin below fails if one starts mapping.
    UNBRIDGED_SETS = {"artillery", "absolute_amazement", "apocalypse", "armageddon",
                      "coercive_persuasion", "fortunata_hypnosis", "gravitational_anchor",
                      "hecatomb", "ragnarok", "soulbound_allegiance", "unbreakable_constraint"}

    def test_unbridged_set_names_refuse_explicitly(self):
        doc = self.v5_from_v4("homecoming-troller")
        converted = reconstruct_build(doc, self.hero, self.hero_sets, self.contract,
                                      self.enhancements, default_io_level=50)
        self.assertFalse(converted["ok"])
        self.assertEqual({i["reason"] for i in converted["issues"]}, {"missing_hero_enhancement"})

    def test_sidekicks_homecoming_controller_with_four_pools_imports_whole(self):
        doc = self.v5_from_v4("homecoming-troller")
        for bucket in [doc["build"]["primary"], doc["build"]["secondary"], *doc["build"]["pools"]]:
            for power in bucket["powers"]:
                power["slots"] = [None if sl and sl.get("setId") in self.UNBRIDGED_SETS else sl
                                  for sl in power["slots"]]
        converted = reconstruct_build(doc, self.hero, self.hero_sets, self.contract,
                                      self.enhancements, incarnate_catalog=self.incarnates,
                                      default_io_level=50)
        self.assertTrue(converted["ok"], converted["issues"][:5])
        build = converted["build"]
        self.assertEqual(build["pools"], ["Pool.Leaping", "Pool.Leadership",
                                          "Pool.Fighting", "Pool.Flight"])
        # The sample picks powers only from Leaping and Leadership so far.
        sets = {p["full_name"].rsplit(".", 1)[0] for p in build["powers"]}
        self.assertLessEqual({"Pool.Leaping", "Pool.Leadership"}, sets)
        self.assertIn("Pool.Leadership.Defense", [p["full_name"] for p in build["powers"]])
        picked = sum(len(s["powers"]) for s in [doc["build"]["primary"], doc["build"]["secondary"]]
                     + doc["build"]["pools"])
        self.assertEqual(len([p for p in build["powers"]
                              if not p["full_name"].startswith("Inherent.")]), picked)

    def test_renamed_epic_resolves_by_archetype_and_identical_roster(self):
        # Sidekick: Epic.Melee_Psionic_Mastery (labelled "scrapper");
        # Hero Companion: Epic.Psionic_Mastery_ScrapStalk, which Stalkers take.
        doc = copy.deepcopy(self.source)
        doc["build"]["epicPool"] = {"id": "melee_psionic_mastery", "powers": [
            {"internalName": "Mental_Blast", "level": 35, "slots": [None]}]}
        doc["build"].pop("attackChains")
        converted = self.reconstruct(doc)
        self.assertTrue(converted["ok"], converted["issues"])
        self.assertEqual(converted["build"]["epic"], "Epic.Psionic_Mastery_ScrapStalk")
        self.assertIn("Epic.Psionic_Mastery_ScrapStalk.Mental_Blast",
                      [p["full_name"] for p in converted["build"]["powers"]])

    def test_another_archetypes_epic_is_refused_even_through_the_alias(self):
        # Epic.Controller_Dark_Mastery reaches our Epic.Dark_Mastery_Controller
        # through Sidekick's alias table, but a Stalker may not take it.
        doc = copy.deepcopy(self.source)
        doc["build"].pop("attackChains")
        doc["build"]["epicPool"] = {"id": "controller_dark_mastery", "powers": [
            {"internalName": "Dark_Blast", "level": 35, "slots": [None]}]}
        converted = self.reconstruct(doc)
        self.assertFalse(converted["ok"])
        self.assertNotIn("build", converted)
        self.assertIn("build.epicPool", [i["location"] for i in converted["issues"]])

    def test_sidekicks_own_homecoming_inherents_land_on_hc_granted_powers(self):
        # Sidekick's v4 Homecoming Controller sample carries real slotted
        # inherents. v5 writes the same objects without the old "name" field.
        sample = json.loads((self.checkout / "fixtures/skif/v4/homecoming-troller.skif")
                            .read_text(encoding="utf-8"))
        doc = copy.deepcopy(self.source)
        doc["build"]["inherents"] = [{k: v for k, v in power.items() if k != "name"}
                                     for power in sample["build"]["inherents"]]
        converted = self.reconstruct(doc)
        self.assertTrue(converted["ok"], converted["issues"])
        slotted = {p["full_name"]: [s and (s.get("set_name") or s["piece_name"]) for s in p["slots"]]
                   for p in converted["build"]["powers"] if p["full_name"].startswith("Inherent.")}
        self.assertEqual(slotted, {
            "Inherent.Inherent.Sprint": ["Celerity"],
            "Inherent.Fitness.Swift": ["Run Speed"],
            "Inherent.Fitness.Hurdle": ["Hamidon Origin"],
            "Inherent.Fitness.Health": ["Panacea", "Numina's Convalesence", "Miracle"],
            "Inherent.Fitness.Stamina": ["Performance Shifter"],
        })


    def test_actual_sidekick_homecoming_incarnates_map_exactly(self):
        # The v4 fixture's real Homecoming catalog choices are converted
        # into the v5 {power, active} shape; the core v5 character is unchanged.
        legacy = json.loads((self.checkout / "fixtures/skif/v4/homecoming-troller.skif")
                            .read_text(encoding="utf-8"))
        source = legacy["build"]["incarnates"]
        doc = copy.deepcopy(self.source)
        doc["build"]["incarnates"] = {
            key: {"power": record["powerName"].split(".")[-1], "active": True}
            for key, record in source.items()
        }
        doc["build"]["incarnates"]["destiny"]["active"] = False
        result = self.reconstruct(doc)
        self.assertTrue(result["ok"], result["issues"])
        for slot, record in source.items():
            mapped = result["build"]["incarnates"][slot.title()]
            self.assertEqual(mapped["full_name"], record["powerName"])
            self.assertEqual(mapped["active"], slot != "destiny")

    def test_actual_sidekick_attack_chains_import_as_non_simulated_metadata(self):
        original = copy.deepcopy(self.source)
        result = self.reconstruct(original)
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual(original, self.source)
        chains = result["build"]["sidekick_attack_chains"]
        self.assertEqual(len(chains), 5)
        self.assertEqual([c["id"] for c in chains],
                         [c["id"] for c in original["build"]["attackChains"]])
        for source, mapped in zip(original["build"]["attackChains"], chains):
            self.assertEqual(mapped["source_powers"], source["powers"])
            self.assertEqual(len(mapped["powers"]), len(source["powers"]))
        self.assertEqual(chains[0]["powers"], [
            "Stalker_Melee.Energy_Melee.Total_Focus",
            "Stalker_Melee.Energy_Melee.Energy_Transfer",
        ])

    def test_actual_game_data_resolves_all_seven_selected_powers(self):
        supported = copy.deepcopy(self.source)
        supported["build"].pop("attackChains")
        converted = self.reconstruct(supported)
        self.assertTrue(converted["ok"], converted["issues"])
        build = converted["build"]
        self.assertEqual(build["archetype"], "Class_Stalker")
        self.assertEqual((build["primary"], build["secondary"]),
                         ("Stalker_Melee.Energy_Melee", "Stalker_Defense.Energy_Aura"))
        self.assertEqual(len(build["powers"]), 7)
        self.assertEqual([p["pick_level"] for p in build["powers"]],
                         [1, 6, 12, 18, 26, 32, 1])
        self.assertTrue(all(p["full_name"] in self.hero for p in build["powers"]))
        self.assertTrue(all(p["earned_slot_count"] == 0 for p in build["powers"]))
        self.assertFalse(converted["editor_imported"])

    def test_offline_command_exposes_native_reconstruction_without_saving(self):
        supported = copy.deepcopy(self.source)
        supported["build"].pop("attackChains")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "character.skif"
            path.write_text(json.dumps(supported), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                code = preview_main([str(path), "--sidekick-contract", str(self.contract),
                                     "--reconstruct"])
            report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["build"]["powers"]), 7)


if __name__ == "__main__":
    unittest.main()
