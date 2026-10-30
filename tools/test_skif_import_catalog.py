"""The offline preview must see the SAME enhancement catalog the server imports with.

Runs on the shipped data only (no Flask, no network). The server builds its
lookup through server/import_catalog.py; the CLI must reuse that one copy and
add nothing but the common IOs the server resolves by a separate map.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
from preview_skif import _enhancement_lookups


class OfflineImportCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lookup = _enhancement_lookups()

    def test_attuned_set_piece_resolves_to_its_crafted_record(self):
        attuned = self.lookup["Attuned_Achilles_Heel_C"]
        self.assertEqual(attuned["piece_uid"], "Crafted_Achilles_Heel_C")
        self.assertTrue(attuned["set_uid"])

    def test_common_ios_resolve_but_are_never_aliased_to_attuned(self):
        self.assertEqual(self.lookup["Crafted_Accuracy"]["piece_uid"], "Crafted_Accuracy")
        invented = [uid for uid in self.lookup
                    if uid.startswith("Attuned_") and uid[len("Attuned_"):] in
                    {"Accuracy", "Damage", "Recharge", "Defense_Buff"}]
        self.assertEqual(invented, [])

    def test_special_origins_carry_their_origin_set_like_the_server(self):
        nucleolus = self.lookup["Hamidon_Damage_Accuracy"]
        self.assertEqual((nucleolus["set_uid"], nucleolus["set_name"]),
                         ("Hamidon_Origin", "Hamidon Origin"))
        self.assertEqual(self.lookup["Dsync_Damage_Accuracy"]["set_uid"], "DSync_Origin")


if __name__ == "__main__":
    unittest.main()
