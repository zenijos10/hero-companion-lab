"""Test the read-only SKIF -> Hero Companion preview against explicit ID evidence."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from sidekick_preview import preview_build, PreviewContractError


def document(powers=None, **extra):
    build = {
        "name": "Inspection only", "dataset": "homecoming",
        "archetype": "blaster", "level": 50,
        "primary": {"id": "blaster/dual-pistols", "powers": powers if powers is not None else [
            {"internalName": "Pistols", "level": 1, "slots": [None]}]},
        "secondary": {"id": "blaster/fire-manipulation", "powers": []},
    }
    build.update(extra)
    return {"version": 5, "build": build}


class SidekickPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "powersets/blaster/primary").mkdir(parents=True)
        (self.root / "powersets/blaster/secondary").mkdir(parents=True)
        self.shards = [
            {"id": "blaster/dual-pistols",
             "path": "powersets/blaster/primary/dual-pistols.json"},
            {"id": "blaster/fire-manipulation",
             "path": "powersets/blaster/secondary/fire-manipulation.json"},
        ]
        self._put("powersets/blaster/primary/dual-pistols.json", {
            "id": "blaster/dual-pistols", "setPath": "Blaster_Ranged.Dual_Pistols",
            "archetype": "blaster", "category": "primary",
            "powers": [{"internalName": "Pistols"}, {"internalName": "Suppressive_Fire"}]})
        self._put("powersets/blaster/secondary/fire-manipulation.json", {
            "id": "blaster/fire-manipulation",
            "setPath": "Blaster_Support.Fire_Manipulation",
            "archetype": "blaster", "category": "secondary", "powers": []})
        self._put("manifest.json", {"dataset": "homecoming", "shards": self.shards})
        self._put("mids-names.json", {"nameReverse": {}, "nameMap": {}})
        self.powers = {
            "Blaster_Ranged.Dual_Pistols.Pistols": {"display_name": "Pistols"},
            "Blaster_Ranged.Dual_Pistols.Suppressive_Fire": {"display_name": "Suppressive Fire"},
        }

    def _put(self, relative, data):
        (self.root / relative).write_text(json.dumps(data), encoding="utf-8")

    def test_exact_verified_power_resolves_without_editing_document(self):
        doc = document()
        before = json.dumps(doc, sort_keys=True)
        result = preview_build(doc, self.powers, self.root)
        self.assertEqual(result["resolved"][0]["hero_power"], "Blaster_Ranged.Dual_Pistols.Pistols")
        self.assertEqual(result["unresolved"], [])
        self.assertFalse(result["ready_for_import"])  # preview must never claim a playable import
        self.assertEqual(json.dumps(doc, sort_keys=True), before)

    def test_mids_reverse_map_handles_rotated_power_names(self):
        self._put("mids-names.json", {
            "nameReverse": {"blaster_ranged.dual_pistols": {
                "suppressive_fire": "Mids_Old_Name"}},
            "nameMap": {"blaster_ranged.dual_pistols": {
                "mids_old_name": "Suppressive_Fire"}}})
        self.powers["Blaster_Ranged.Dual_Pistols.Mids_Old_Name"] = {"display_name": "Suppressive Fire"}
        result = preview_build(document([{"internalName": "Suppressive_Fire", "level": 4, "slots": []}]),
                               self.powers, self.root)
        self.assertEqual(result["resolved"][0]["hero_power"],
                         "Blaster_Ranged.Dual_Pistols.Mids_Old_Name")
        self.assertEqual(result["unresolved"], [])

    def test_missing_alias_does_not_resolve_another_powers_name(self):
        self._put("mids-names.json", {
            "nameReverse": {},
            "nameMap": {"blaster_ranged.dual_pistols": {
                "pistols": "Another_Power"}}})
        result = preview_build(document(), self.powers, self.root)
        self.assertEqual(result["resolved"], [])
        self.assertIn("power_name_conflict", [x["reason"] for x in result["unresolved"]])

    def test_unknown_or_unlisted_powers_remain_unresolved(self):
        result = preview_build(document([
            {"internalName": "Unlisted", "level": 1, "slots": []},
            {"internalName": "Suppressive_Fire", "level": 4, "slots": []},
        ]), self.powers, self.root)
        self.assertEqual(len(result["resolved"]), 1)
        self.assertIn("unknown_source_power", [x["reason"] for x in result["unresolved"]])

    def test_filled_slots_and_preserved_nonpower_state_are_never_dropped_silently(self):
        doc = document([
            {"internalName": "Pistols", "level": 1, "slots": [
                {"type": "io-generic", "stat": "accuracy", "level": 50}]}],
            stances={"ammo": True}, incarnates={"alpha": {"power": "alpha/example", "active": True}},
            attackChains=[{"id": "a", "name": "Opener", "powers": ["x:y"]}])
        result = preview_build(doc, self.powers, self.root)
        reasons = [r["reason"] for r in result["unresolved"]]
        self.assertEqual(reasons.count("enhancement_not_mapped"), 1)
        self.assertEqual(reasons.count("state_not_mapped"), 3)
        self.assertFalse(result["ready_for_import"])

    def test_shard_identity_mismatch_blocks_bad_mapping(self):
        self._put("powersets/blaster/primary/dual-pistols.json", {
            "id": "blaster/another-set", "setPath": "Blaster_Ranged.Dual_Pistols",
            "powers": [{"internalName": "Pistols"}]})
        result = preview_build(document(), self.powers, self.root)
        self.assertEqual(result["resolved"], [])
        self.assertIn("source_identity_mismatch", [x["reason"] for x in result["unresolved"]])

    def test_unmapped_set_and_non_homecoming_refuse_explicitly(self):
        doc = document()
        doc["build"]["primary"]["id"] = "blaster/unrecognized-set"
        result = preview_build(doc, self.powers, self.root)
        self.assertIn("unknown_source_set", [x["reason"] for x in result["unresolved"]])
        doc["build"]["dataset"] = "rebirth"
        with self.assertRaises(PreviewContractError):
            preview_build(doc, self.powers, self.root)

    def test_manifest_traversal_and_missing_contract_refuse(self):
        self.shards[0]["path"] = "../outside.json"
        self._put("manifest.json", {"dataset": "homecoming", "shards": self.shards})
        with self.assertRaises(PreviewContractError):
            preview_build(document(), self.powers, self.root)
        (self.root / "mids-names.json").unlink()
        with self.assertRaises(PreviewContractError):
            preview_build(document(), self.powers, self.root)


if __name__ == "__main__":
    unittest.main()
