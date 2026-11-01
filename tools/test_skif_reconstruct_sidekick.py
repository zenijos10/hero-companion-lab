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

    @classmethod
    def reconstruct(cls, doc):
        return reconstruct_build(doc, cls.hero, cls.hero_sets, cls.contract,
                                 cls.enhancements)

    def test_actual_sidekick_attack_chain_remains_a_blocker(self):
        original = copy.deepcopy(self.source)
        result = self.reconstruct(original)
        self.assertFalse(result["ok"])
        self.assertNotIn("build", result)
        self.assertIn("unsupported_source_state", [v["reason"] for v in result["issues"]])
        self.assertEqual(original, self.source)

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
