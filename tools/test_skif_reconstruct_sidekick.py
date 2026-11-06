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
