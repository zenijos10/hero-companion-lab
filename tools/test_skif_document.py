"""Independent, dependency-free compatibility contract for Sidekick SKIF v5."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from skif_document import SkifFormatError, load_document, dump_document


def sample():
    return {
        "version": 5,
        "meta": {"author": "test", "unrecognized": [False, None, 7]},
        "authoredAgainst": {"dataset": "homecoming", "contractSchema": 3, "datasetSchema": 9},
        "build": {
            "name": "Test", "dataset": "homecoming", "archetype": "corruptor", "level": 50,
            "primary": {"id": "corruptor/dual-pistols", "powers": [
                {"internalName": "Pistols", "level": 1,
                 "slots": [None, {"type": "io-set", "setId": "set/example", "pieceNum": 2,
                                  "attuned": True, "booster": 3, "futureOption": "kept"},
                           {"type": "io-generic", "stat": "recharge", "level": 45},
                           {"type": "special", "category": "hamidon", "id": "nucleolus", "relativeLevel": 3},
                           {"type": "origin", "stat": "accuracy", "tier": "SO", "relativeLevel": -2}]}]},
            "secondary": {"id": "corruptor/empathy", "powers": []},
            "pools": [], "inherents": [],
            "stances": {"ammo": True},
            "procOverrides": {"x:y:0": {"enabled": False, "mode": "auto"}},
            "attackChains": [{"id": "a", "name": "Attack", "powers": ["x:y"]}],
            "futureBuildKey": {"nested": [1, "keep me"]},
        },
        "futureFileKey": ["keep"],
    }


class SkifDocumentTests(unittest.TestCase):
    def test_round_trip_preserves_every_field_and_does_not_mutate_input(self):
        original = sample()
        snapshot = copy.deepcopy(original)
        parsed = load_document(original)
        self.assertEqual(original, snapshot)
        self.assertIsNot(parsed, original)
        self.assertEqual(load_document(dump_document(parsed)), original)

    def test_dump_is_stable_and_unicode_safe(self):
        doc = sample()
        doc["build"]["name"] = "Héros ✦"
        encoded = dump_document(doc)
        self.assertEqual(encoded, dump_document(load_document(encoded)))
        self.assertIn("Héros ✦", encoded)
        self.assertTrue(encoded.endswith("\n"))

    def test_rejects_invalid_json_and_duplicate_keys(self):
        for raw in ("{", '{"version":5,"version":5,"build":{}}',
                    '{"version":NaN,"build":{}}'):
            with self.subTest(raw=raw), self.assertRaises(SkifFormatError):
                load_document(raw)

    def test_rejects_unsupported_version_and_wrong_structure(self):
        bad = [{"version": 4, "build": sample()["build"]},
               {"version": True, "build": sample()["build"]},
               {"version": 5, "build": []},
               {"version": 5, "build": {"dataset": "homecoming", "level": 50, "pools": {}}}]
        for doc in bad:
            with self.subTest(doc=doc), self.assertRaises(SkifFormatError):
                load_document(doc)

    def test_rejects_invalid_slot_tag_or_negative_booster(self):
        for slot in ({"type": "unknown"}, {"type": []},
                     {"type": "io-generic", "stat": "accuracy", "booster": -1},
                     {"type": "io-set", "setId": "a", "pieceNum": 1, "level": 0}):
            doc = sample()
            doc["build"]["primary"]["powers"][0]["slots"] = [slot]
            with self.subTest(slot=slot), self.assertRaises(SkifFormatError):
                load_document(doc)

    def test_rejects_what_if_layer_and_dataset_disagreement(self):
        doc = sample()
        doc["build"]["whatIfBuffs"] = {"magnitude": 1}
        with self.assertRaises(SkifFormatError):
            load_document(doc)
        doc = sample()
        doc["authoredAgainst"]["dataset"] = "rebirth"
        with self.assertRaises(SkifFormatError):
            load_document(doc)

    def test_optional_strings_accept_null_and_optional_booleans_may_be_omitted(self):
        doc = sample()
        power = doc["build"]["primary"]["powers"][0]
        power.update(powerset=None, activeSubPower=None)
        power.pop("isActive", None)
        power["slots"][1].pop("attuned", None)
        self.assertEqual(load_document(dump_document(doc)), doc)

    def test_optional_boolean_null_is_invalid_in_sidekick_v5(self):
        # Sidekick defines both as bool with serde(default), not Option<bool>.
        for field in ("isActive", "attuned"):
            doc = sample()
            power = doc["build"]["primary"]["powers"][0]
            if field == "isActive":
                power[field] = None
            else:
                power["slots"][1][field] = None
            with self.subTest(field=field), self.assertRaises(SkifFormatError):
                load_document(doc)

    def test_rejects_non_boolean_optional_flag(self):
        doc = sample()
        doc["build"]["primary"]["powers"][0]["isActive"] = "yes"
        with self.assertRaises(SkifFormatError):
            load_document(doc)

    def test_retains_new_vocabulary_in_known_structural_fields(self):
        doc = sample()
        doc["build"]["stances"]["new-ammo-mode"] = False
        doc["build"]["primary"]["id"] = "future-powerset/name"
        doc["build"]["primary"]["powers"][0]["internalName"] = "Future_Power"
        self.assertEqual(load_document(dump_document(doc)), doc)


if __name__ == "__main__":
    unittest.main()
