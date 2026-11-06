"""Sidekick enhancement identity bridge: no guessed UIDs or silent substitutions."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from sidekick_enhancements import EnhancementContractError, EnhancementResolver


class EnhancementBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.boosts = {
            "Crafted_Achilles_Heel_C": {"kind": "io-set", "set": "achilles_heel",
                                         "piece": 3, "attuned": False},
            "Attuned_Achilles_Heel_C": {"kind": "io-set", "set": "achilles_heel",
                                         "piece": 3, "attuned": True},
            "Superior_Attuned_Superior_Critical_Strikes_A": {
                "kind": "io-set", "set": "superior_critical_strikes",
                "piece": 1, "attuned": True},
            "Crafted_Recharge": {"kind": "common-io", "stats": ["Recharge"], "level": None},
            "Crafted_Recharge_50": {"kind": "common-io", "stats": ["Recharge"], "level": 50},
            "Crafted_Heal": {"kind": "common-io", "stats": ["Healing", "Absorb"], "level": None},
            "Hamidon_Damage_Accuracy": {"kind": "special", "family": "hamidon", "id": "nucleolus"},
            "Magic_Accuracy": {"kind": "origin", "stats": ["Accuracy"],
                                "origins": ["Magic"], "tier": "SO"},
        }
        self.allowed = {
            "Crafted_Achilles_Heel_C": {"piece_uid": "Crafted_Achilles_Heel_C", "set_uid": "AH"},
            "Attuned_Achilles_Heel_C": {"piece_uid": "Crafted_Achilles_Heel_C", "set_uid": "AH"},
            "Superior_Attuned_Superior_Critical_Strikes_A": {
                "piece_uid": "Superior_Attuned_Superior_Critical_Strikes_A", "set_uid": "CS"},
            "Crafted_Recharge": {"piece_uid": "Crafted_Recharge"},
            "Crafted_Heal": {"piece_uid": "Crafted_Heal"},
            "Hamidon_Damage_Accuracy": {"piece_uid": "Hamidon_Damage_Accuracy"},
        }
        self.write()
        self.bridge = EnhancementResolver(self.root, self.allowed)

    def write(self):
        (self.root / "boost-index.json").write_text(json.dumps(self.boosts), encoding="utf-8")
        (self.root / "enhancements.json").write_text(
            json.dumps({"commonIoTypes": ["Recharge", "Healing", "Damage", "Accuracy"]}),
            encoding="utf-8")

    def test_attuned_and_crafted_are_distinct(self):
        for attuned, expected in ((False, "Crafted_Achilles_Heel_C"),
                                  (True, "Attuned_Achilles_Heel_C")):
            with self.subTest(attuned=attuned):
                result, issue = self.bridge.resolve({
                    "type": "io-set", "setId": "achilles_heel",
                    "pieceNum": 3, "attuned": attuned, "level": 50,
                    "booster": 2,
                })
                self.assertIsNone(issue)
                self.assertEqual(result["source_uid"], expected)
                self.assertEqual(result["hero_slot"]["piece_uid"], "Crafted_Achilles_Heel_C")
                self.assertEqual(result["attuned"], attuned)
                self.assertEqual(result["io_level"], 50)
                self.assertEqual(result["booster"], 2)

    def test_superior_attuned_exact_identity_and_zero_based_piece_refused(self):
        result, issue = self.bridge.resolve({
            "type": "io-set", "setId": "superior_critical_strikes",
            "pieceNum": 1, "attuned": True,
        })
        self.assertIsNone(issue)
        self.assertEqual(result["source_uid"], "Superior_Attuned_Superior_Critical_Strikes_A")
        self.assertTrue(result["attuned"])
        result, issue = self.bridge.resolve({
            "type": "io-set", "setId": "achilles_heel", "pieceNum": 0,
        })
        self.assertIsNone(result)
        self.assertEqual(issue, "unknown_enhancement_identity")

    def test_generic_uses_exact_source_stat_not_similarity(self):
        result, issue = self.bridge.resolve({"type": "io-generic", "stat": "Healing", "level": 45})
        self.assertIsNone(issue)
        self.assertEqual(result["source_uid"], "Crafted_Heal")
        self.assertEqual(result["io_level"], 45)
        result, issue = self.bridge.resolve({"type": "io-generic", "stat": "Heal", "level": 45})
        self.assertIsNone(result)
        self.assertEqual(issue, "unknown_enhancement_identity")

    def test_special_identity_does_not_guess_relative_level(self):
        result, issue = self.bridge.resolve({
            "type": "special", "category": "hamidon",
            "id": "nucleolus", "relativeLevel": 3})
        self.assertIsNone(issue)
        self.assertEqual(result["source_uid"], "Hamidon_Damage_Accuracy")
        self.assertEqual(result["relative_level"], 3)
        self.assertNotIn("io_level", result)

    def test_missing_hero_uid_and_origin_are_explicitly_unresolved(self):
        result, issue = self.bridge.resolve({
            "type": "origin", "stat": "Accuracy", "tier": "SO"})
        self.assertIsNone(result)
        self.assertEqual(issue, "missing_hero_enhancement")
        result, issue = self.bridge.resolve({
            "type": "io-set", "setId": "missing", "pieceNum": 1})
        self.assertIsNone(result)
        self.assertEqual(issue, "unknown_enhancement_identity")

    def test_ambiguous_source_contract_refuses_to_pick_arbitrarily(self):
        self.boosts["Crafted_Recharge_Alias"] = {
            "kind": "common-io", "stats": ["Recharge"], "level": None}
        self.allowed["Crafted_Recharge_Alias"] = {"piece_uid": "Crafted_Recharge_Alias"}
        self.write()
        bridge = EnhancementResolver(self.root, self.allowed)
        result, issue = bridge.resolve({"type": "io-generic", "stat": "Recharge"})
        self.assertIsNone(result)
        self.assertEqual(issue, "ambiguous_enhancement_identity")

    def test_null_optional_fields_read_as_absent_never_none(self):
        result, issue = self.bridge.resolve({
            "type": "io-set", "setId": "achilles_heel", "pieceNum": 3,
            "level": None, "booster": None})
        self.assertIsNone(issue)
        self.assertNotIn("io_level", result)
        self.assertEqual(result["booster"], 0)
        result, issue = self.bridge.resolve({
            "type": "special", "category": "hamidon", "id": "nucleolus",
            "relativeLevel": None})
        self.assertIsNone(issue)
        self.assertEqual(result["relative_level"], 0)

    def bridged(self, hero_sets, boosts):
        self.boosts.update(boosts)
        self.write()
        hero = dict(self.allowed)
        for set_uid, letters in hero_sets.items():
            for letter, uid in letters.items():
                hero[uid] = {"set_uid": set_uid, "piece_uid": uid}
        return EnhancementResolver(self.root, hero)

    def test_renamed_piece_uid_bridges_by_the_sets_own_id_and_piece_number(self):
        # Our Mids-derived Artillery pieces are Crafted_Shrapnel_*; the game's
        # (Sidekick's) are Crafted_Artillery_*. Same set id, same piece number.
        bridge = self.bridged({"Artillery": {"A": "Crafted_Shrapnel_A", "B": "Crafted_Shrapnel_B"}},
                              {"Crafted_Artillery_B": {"kind": "io-set", "set": "artillery",
                                                       "piece": 2, "attuned": False}})
        result, issue = bridge.resolve({"type": "io-set", "setId": "artillery",
                                        "pieceNum": 2, "level": 50})
        self.assertIsNone(issue)
        self.assertEqual((result["source_uid"], result["hero_slot"]["piece_uid"]),
                         ("Crafted_Artillery_B", "Crafted_Shrapnel_B"))

    def test_attuned_purple_under_the_superior_prefix_is_the_same_set_attuned(self):
        bridge = self.bridged({"Apocalypse": {"A": "Crafted_Apocalypse_A"}},
                              {"Superior_Attuned_Apocalypse_A": {
                                  "kind": "io-set", "set": "apocalypse", "piece": 1,
                                  "attuned": True}})
        result, issue = bridge.resolve({"type": "io-set", "setId": "apocalypse",
                                        "pieceNum": 1, "attuned": True})
        self.assertIsNone(issue)
        self.assertEqual(result["hero_slot"]["piece_uid"], "Crafted_Apocalypse_A")
        self.assertTrue(result["attuned"])

    def test_bridge_needs_a_matching_set_and_a_real_piece(self):
        bridge = self.bridged({"Artillery": {"A": "Crafted_Shrapnel_A"},
                               "Superior_Blistering_Cold": {"A": "Superior_Attuned_Blistering_Cold_A"}},
                              {"Crafted_Artillery_F": {"kind": "io-set", "set": "artillery",
                                                       "piece": 6, "attuned": False},
                               "Crafted_Unknown_A": {"kind": "io-set", "set": "unknown_set",
                                                     "piece": 1, "attuned": False}})
        for piece in ({"type": "io-set", "setId": "artillery", "pieceNum": 6, "level": 50},
                      {"type": "io-set", "setId": "unknown_set", "pieceNum": 1, "level": 50}):
            with self.subTest(piece=piece):
                self.assertEqual(bridge.resolve(piece), (None, "missing_hero_enhancement"))

    def test_corrupt_or_missing_contract_is_a_hard_failure(self):
        (self.root / "boost-index.json").unlink()
        with self.assertRaises(EnhancementContractError):
            EnhancementResolver(self.root, self.allowed)
        self.boosts["Crafted_Recharge"] = ["invalid"]
        self.write()
        with self.assertRaises(EnhancementContractError):
            EnhancementResolver(self.root, self.allowed)


if __name__ == "__main__":
    unittest.main()
