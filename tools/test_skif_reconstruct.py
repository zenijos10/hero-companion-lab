"""Safe SKIF v5 -> native HC build reconstruction contract.

Identity must have been independently proven by the read-only Sidekick preview.
A reconstruction result may be used for analysis only when no source state is
silently dropped. No editor or save is mutated.
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from sidekick_reconstruct import reconstruct_build


def fixture():
    return {"version": 5, "build": {
        "dataset": "homecoming", "name": "Precision Test", "archetype": "blaster",
        "origin": "magic", "level": 50,
        "primary": {"id": "blaster/dual-pistols", "powers": [{
            "internalName": "Pistols", "level": 1, "slots": [
                None, {"type": "io-generic", "stat": "Recharge",
                       "level": 50, "booster": 2},
                {"type": "io-set", "setId": "achilles_heel", "pieceNum": 3,
                 "attuned": True},
                {"type": "special", "category": "hamidon",
                 "id": "nucleolus", "relativeLevel": 3},
            ]}]},
        "secondary": {"id": "blaster/fire-manipulation", "powers": []},
        "pools": [{"id": "pool/flight", "powers": []}],
    }}


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for bucket in ("blaster/primary", "blaster/secondary", "pool/pool"):
            (self.root / "powersets" / bucket).mkdir(parents=True)
        self.shards = [
            ("blaster/dual-pistols", "Blaster_Ranged.Dual_Pistols",
             "blaster/primary/dual-pistols", "blaster", "primary", ["Pistols"]),
            ("blaster/fire-manipulation", "Blaster_Support.Fire_Manipulation",
             "blaster/secondary/fire-manipulation", "blaster", "secondary", []),
            ("pool/flight", "Pool.Flight", "pool/pool/flight",
             None, "pool", []),
        ]
        shards = []
        for ident, path, rel, archetype, category, powers in self.shards:
            target = "powersets/" + rel + ".json"
            shards.append({"id": ident, "path": target})
            self._write(target, {"id": ident, "setPath": path,
                                 "archetype": archetype, "category": category,
                                 "powers": [{"internalName": p} for p in powers]})
        self._write("manifest.json", {"dataset": "homecoming", "shards": shards})
        self._write("mids-names.json", {"nameMap": {}, "nameReverse": {}})
        self._write("archetypes.json", {"archetypes": {
            "blaster": {"stats": {"className": "Class_Blaster"}}}})
        self._write("boost-index.json", {
            "Crafted_Recharge": {"kind": "common-io", "level": None, "stats": ["Recharge"]},
            "Attuned_Achilles_Heel_C": {"kind": "io-set", "set": "achilles_heel",
                                        "piece": 3, "attuned": True},
            "Hamidon_Damage_Accuracy": {"kind": "special",
                                        "family": "hamidon", "id": "nucleolus"}})
        self._write("enhancements.json", {"commonIoTypes": ["Recharge"]})
        self.hero = {"Blaster_Ranged.Dual_Pistols.Pistols": {
            "full_name": "Blaster_Ranged.Dual_Pistols.Pistols",
            "display_name": "Pistols", "powerset_full_name": "Blaster_Ranged.Dual_Pistols",
            "accepted_set_category_ids": [7], "accepted_set_categories": ["Ranged"],
            "power_type": "Click", "level_available": 1}}
        self.hero_sets = {"by_archetype": {"Class_Blaster": {
            "primary": [{"full_name": "Blaster_Ranged.Dual_Pistols"}],
            "secondary": [{"full_name": "Blaster_Support.Fire_Manipulation"}],
            "epic": []}},
            "pools": [{"full_name": "Pool.Flight"}]}
        self.pieces = {
            "Crafted_Recharge": {"piece_uid": "Crafted_Recharge", "piece_name": "Recharge"},
            "Attuned_Achilles_Heel_C": {
                "set_uid": "Crafted_Achilles_Heel", "set_name": "Achilles' Heel",
                "piece_uid": "Crafted_Achilles_Heel_C", "piece_name": "Chance for -Res"},
            "Hamidon_Damage_Accuracy": {
                "set_uid": "Hamidon_Origin", "set_name": "Hamidon Origin",
                "piece_uid": "Hamidon_Damage_Accuracy", "piece_name": "Nucleolus Exposure"},
        }

    def _write(self, path, obj):
        (self.root / path).write_text(json.dumps(obj), encoding="utf-8")

    def convert(self, doc=None, **kwargs):
        return reconstruct_build(
            fixture() if doc is None else doc, self.hero, self.hero_sets,
            self.root, self.pieces, **kwargs)

    def test_native_build_keeps_class_all_powersets_slot_positions_and_levels(self):
        source = fixture()
        snapshot = copy.deepcopy(source)
        result = self.convert(source)
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual(source, snapshot)
        b = result["build"]
        self.assertEqual((b["archetype"], b["primary"], b["secondary"], b["pools"],
                          b["epic"], b["char_level"]),
                         ("Class_Blaster", "Blaster_Ranged.Dual_Pistols",
                          "Blaster_Support.Fire_Manipulation", ["Pool.Flight"], None, 50))
        self.assertEqual(b["origin"], "magic")
        self.assertEqual(len(b["powers"]), 1)
        p = b["powers"][0]
        self.assertEqual(p["full_name"], "Blaster_Ranged.Dual_Pistols.Pistols")
        self.assertEqual(p["pick_level"], 1)
        self.assertEqual(p["earned_slot_count"], 4)
        self.assertIsNone(p["slots"][0])
        self.assertEqual(p["slots"][1]["io_level"], 50)
        self.assertEqual(p["slots"][1]["boost"], 2)
        self.assertTrue(p["slots"][2]["attuned"])
        self.assertEqual(p["slots"][2]["piece_uid"], "Crafted_Achilles_Heel_C")
        self.assertNotIn("io_level", p["slots"][2])
        self.assertEqual(p["slots"][3]["io_level"], 53)
        self.assertEqual(b["incarnates"], {})
        self.assertFalse(result["editor_imported"])  # library conversion, not UI mutation
        self.assertEqual(result["source_skif"], source)

    def test_missing_generic_level_requires_explicit_default(self):
        doc = fixture()
        del doc["build"]["primary"]["powers"][0]["slots"][1]["level"]
        refusal = self.convert(doc)
        self.assertFalse(refusal["ok"])
        self.assertNotIn("build", refusal)
        self.assertIn("io_level_not_embedded",
                      [p["reason"] for p in refusal["issues"]])
        converted = self.convert(doc, default_io_level=42)
        self.assertTrue(converted["ok"], converted["issues"])
        self.assertEqual(converted["build"]["powers"][0]["slots"][1]["io_level"], 42)

    def test_zero_empty_and_granted_slots_stay_positional(self):
        doc = fixture()
        power = doc["build"]["primary"]["powers"][0]
        power["level"] = 0
        power["slots"] = [None, None]
        result = self.convert(doc)
        self.assertTrue(result["ok"], result["issues"])
        p = result["build"]["powers"][0]
        self.assertEqual(p["pick_level"], 0)
        self.assertEqual(p["slots"], [None, None])
        self.assertEqual(p["earned_slot_count"], 2)

    def test_nonrepresentable_state_is_explicitly_blocked_never_partially_imported(self):
        alterations = [
            ("stances", {"ammo": True}),
            ("incarnates", {"alpha": {"power": "Alpha.Example", "active": True}}),
            ("inherents", [{"internalName": "Health", "level": 0, "slots": []}]),
            ("slotOrder", [{"powerName": "Pistols", "slotIndex": 1}]),
            ("progress", {"crafted": ["enhancement-key"]}),
            ("futureState", {"mystery": 1}),
        ]
        for key, value in alterations:
            doc = fixture()
            doc["build"][key] = value
            with self.subTest(field=key):
                result = self.convert(doc)
                self.assertFalse(result["ok"], result)
                self.assertNotIn("build", result)
                self.assertIn("unsupported_source_state",
                              [p["reason"] for p in result["issues"]])

    def test_attack_chains_preserve_source_order_and_verified_power_mappings(self):
        doc = fixture()
        doc["build"]["attackChains"] = [
            {"id": "opener", "name": "The opener", "powers": [
                "blaster/dual-pistols:Pistols", "blaster/dual-pistols:Pistols"]},
            {"id": "idle", "name": "No powers", "powers": []},
        ]
        before = copy.deepcopy(doc)
        res = self.convert(doc)
        self.assertTrue(res["ok"], res["issues"])
        self.assertEqual(doc, before)
        self.assertEqual(res["build"]["sidekick_attack_chains"], [
            {"id": "opener", "name": "The opener",
             "powers": ["Blaster_Ranged.Dual_Pistols.Pistols"] * 2,
             "source_powers": ["blaster/dual-pistols:Pistols"] * 2},
            {"id": "idle", "name": "No powers", "powers": [], "source_powers": []},
        ])

    def test_unknown_or_unselected_chain_powers_block_the_entire_build(self):
        for ref in ("blaster/dual-pistols:Imaginary",
                    "blaster/fire-manipulation:Some_Unselected",
                    "madeup"):
            doc = fixture()
            doc["build"]["attackChains"] = [
                {"id": "chain", "name": "Bad", "powers": [ref]}]
            with self.subTest(ref=ref):
                res = self.convert(doc)
                self.assertFalse(res["ok"])
                self.assertNotIn("build", res)
                self.assertIn("unknown_attack_chain_power",
                              [i["reason"] for i in res["issues"]])

    def test_duplicate_ids_or_unrepresented_chain_fields_are_refused(self):
        doc = fixture()
        doc["build"]["attackChains"] = [
            {"id": "same", "name": "One", "powers": []},
            {"id": "same", "name": "Two", "powers": []},
        ]
        result = self.convert(doc)
        self.assertFalse(result["ok"])
        self.assertNotIn("build", result)
        self.assertIn("duplicate_attack_chain_id", [i["reason"] for i in result["issues"]])
        doc = fixture()
        doc["build"]["attackChains"] = [
            {"id": "safe", "name": "One", "powers": [], "futureSwitch": True},
        ]
        result = self.convert(doc)
        self.assertFalse(result["ok"])
        self.assertIn("unsupported_attack_chain_field",
                      [i["reason"] for i in result["issues"]])

    def test_active_subpower_and_unknown_power_fields_refuse(self):
        for changes in ({"isActive": True}, {"activeSubPower": "ModeX"},
                        {"futureFlag": False}):
            doc = fixture()
            doc["build"]["primary"]["powers"][0].update(changes)
            with self.subTest(changes=changes):
                result = self.convert(doc)
                self.assertFalse(result["ok"])
                self.assertNotIn("build", result)

    def test_unknown_power_or_enhancement_refuses_the_entire_build(self):
        doc = fixture()
        doc["build"]["primary"]["powers"][0]["internalName"] = "Imaginary_Power"
        result = self.convert(doc)
        self.assertFalse(result["ok"])
        self.assertNotIn("build", result)
        doc = fixture()
        doc["build"]["primary"]["powers"][0]["slots"][1]["stat"] = "Imaginary"
        result = self.convert(doc)
        self.assertFalse(result["ok"])
        self.assertNotIn("build", result)

    def test_powerset_membership_refuses_mislabeled_primary(self):
        doc = fixture()
        self.hero_sets["by_archetype"]["Class_Blaster"]["primary"] = []
        result = self.convert(doc)
        self.assertFalse(result["ok"])
        self.assertIn("invalid_powerset_for_role", [p["reason"] for p in result["issues"]])

    def test_unknown_archetype_mapping_does_not_guess_class(self):
        self._write("archetypes.json", {"archetypes": {"blaster": {"stats": {}}}})
        result = self.convert()
        self.assertFalse(result["ok"])
        self.assertIn("unknown_archetype", [p["reason"] for p in result["issues"]])

    def test_null_numeric_carries_no_unexpected_none_or_guessed_default(self):
        doc = fixture()
        doc["build"]["primary"]["powers"][0]["slots"][1]["booster"] = None
        doc["build"]["primary"]["powers"][0]["slots"][3]["relativeLevel"] = None
        result = self.convert(doc)
        self.assertTrue(result["ok"], result["issues"])
        self.assertNotIn("boost", result["build"]["powers"][0]["slots"][1])
        self.assertNotIn("io_level", result["build"]["powers"][0]["slots"][3])

    def test_special_origin_grade_outside_50_to_53_refuses(self):
        # The game's HOs exist at 50..53; a -3 would price at x0.70 and a +5
        # as a level-55 HO the game cannot produce. Neither may convert.
        for relative in (-3, -1, 4, 5):
            doc = fixture()
            doc["build"]["primary"]["powers"][0]["slots"][3]["relativeLevel"] = relative
            with self.subTest(relative=relative):
                result = self.convert(doc)
                self.assertFalse(result["ok"])
                self.assertIn("unsupported_special_relative_level",
                              [p["reason"] for p in result["issues"]])
        doc = fixture()
        doc["build"]["primary"]["powers"][0]["slots"][3]["relativeLevel"] = 0
        result = self.convert(doc)
        self.assertTrue(result["ok"], result["issues"])
        self.assertNotIn("boost", result["build"]["powers"][0]["slots"][3])

    def test_booster_on_attuned_io_refuses_rather_than_vanishing(self):
        # Attuned IOs take no boosters (the engine ignores one), so carrying
        # it would silently drop source state.
        doc = fixture()
        doc["build"]["primary"]["powers"][0]["slots"][2]["booster"] = 3
        result = self.convert(doc)
        self.assertFalse(result["ok"])
        self.assertIn("booster_on_attuned_io", [p["reason"] for p in result["issues"]])
        doc["build"]["primary"]["powers"][0]["slots"][2]["booster"] = 0
        self.assertTrue(self.convert(doc)["ok"])


if __name__ == "__main__":
    unittest.main()
