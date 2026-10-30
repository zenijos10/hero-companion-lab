"""Integration smoke against a pinned, separately checked-out Sidekick contract.

Requires a local upstream checkout; no network calls in this test. The GitHub
Actions job checks out a sparse subset of that public repository independently.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from sidekick_preview import preview_build


class RealHomecomingContractTests(unittest.TestCase):
    def test_sidekick_v5_stalker_fixture_resolves_all_seven_powers(self):
        upstream = ROOT / "_sidekick_contract_fixture"
        self.assertTrue((upstream / "contract/homecoming/manifest.json").is_file(),
                        "Run with a sparse Sidekick upstream checkout in _sidekick_contract_fixture")
        fixture = json.loads((upstream / "fixtures/skif/v5/rb5d_browser_pass.skif")
                             .read_text(encoding="utf-8"))
        game_powers = json.loads((ROOT / "data/powers.json").read_text(encoding="utf-8"))
        hero_index = {power["full_name"]: power
                      for group in game_powers.values() for power in group}
        report = preview_build(fixture, hero_index, upstream / "contract/homecoming")
        expected = sum(len(fixture["build"][key]["powers"]) for key in ("primary", "secondary"))
        self.assertEqual(expected, 7, "Pin the fixture's expected input count")
        self.assertEqual(len(report["resolved"]), expected, report["unresolved"])
        self.assertEqual(report["unresolved"],
                         [{"reason": "state_not_mapped",
                           "location": "build.attackChains", "detail": "attackChains"}])
        self.assertFalse(report["ready_for_import"])


    def test_real_boost_index_maps_crafted_attuned_generic_and_hamidon(self):
        from sidekick_enhancements import EnhancementResolver
        upstream = ROOT / "_sidekick_contract_fixture" / "contract/homecoming"
        self.assertTrue((upstream / "boost-index.json").is_file(),
                        "Pinned Sidekick enhancement data must be checked out")
        # The real test uses Hero Companion's existing import catalog, not a
        # mock UID list: a correct Sidekick identity can still be absent in HC.
        sys.path.insert(0, str(ROOT / "tools"))
        from preview_skif import _enhancement_lookups
        bridge = EnhancementResolver(upstream, _enhancement_lookups())
        cases = [
            ({"type": "io-set", "setId": "achilles_heel", "pieceNum": 3,
              "attuned": False, "level": 50}, "Crafted_Achilles_Heel_C"),
            ({"type": "io-set", "setId": "achilles_heel", "pieceNum": 3,
              "attuned": True}, "Attuned_Achilles_Heel_C"),
            ({"type": "io-generic", "stat": "Recharge", "level": 50},
             "Crafted_Recharge"),
            ({"type": "special", "category": "hamidon", "id": "nucleolus",
              "relativeLevel": 3}, "Hamidon_Damage_Accuracy"),
        ]
        for piece, source_uid in cases:
            with self.subTest(piece=piece):
                mapped, issue = bridge.resolve(piece)
                self.assertIsNone(issue)
                self.assertEqual(mapped["source_uid"], source_uid)
                self.assertTrue(mapped["hero_slot"]["piece_uid"])


if __name__ == "__main__":
    unittest.main()
