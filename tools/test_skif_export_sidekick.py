"""SKIF v5 export: a real Sidekick build survives import -> export -> import.

Requires the pinned upstream checkout in _sidekick_contract_fixture (CI job).
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
from preview_skif import _enhancement_lookups
from sidekick_reconstruct import reconstruct_build
from skif_document import dump_document, load_document
from skif_export import export_build


class SidekickExportRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkout = ROOT / "_sidekick_contract_fixture"
        cls.contract = cls.checkout / "contract/homecoming"
        cls.source = json.loads((cls.checkout / "fixtures/skif/v5/rb5d_browser_pass.skif")
                                .read_text(encoding="utf-8"))
        sample = json.loads((cls.checkout / "fixtures/skif/v4/homecoming-troller.skif")
                            .read_text(encoding="utf-8"))
        cls.inherents = [{k: v for k, v in p.items() if k != "name"}
                         for p in sample["build"]["inherents"]]
        powers = json.loads((ROOT / "data/powers.json").read_text(encoding="utf-8"))
        cls.hero = {p["full_name"]: p for group in powers.values() for p in group}
        cls.hero_sets = json.loads((ROOT / "data/powersets.json").read_text(encoding="utf-8"))
        cls.incarnates = json.loads((ROOT / "data/incarnates.json").read_text(encoding="utf-8"))
        cls.pieces = _enhancement_lookups()

    def imported(self, doc):
        result = reconstruct_build(doc, self.hero, self.hero_sets, self.contract, self.pieces,
                                   incarnate_catalog=self.incarnates)
        self.assertTrue(result["ok"], result["issues"])
        return result["build"]

    def export(self, build):
        result = export_build(build, self.hero, self.contract, self.hero_sets,
                              hero_piece_by_uid=self.pieces)
        self.assertTrue(result["ok"], result["issues"])
        return result

    def rich_source(self):
        doc = copy.deepcopy(self.source)
        doc["build"]["inherents"] = copy.deepcopy(self.inherents)
        doc["build"]["incarnates"] = {
            "alpha": {"power": "Incarnate.Alpha.Agility_Core_Paragon", "active": True},
            "destiny": {"power": "Incarnate.Destiny.Ageless_Core_Epiphany", "active": False}}
        return doc

    def test_real_sidekick_build_round_trips_to_the_identical_hc_build(self):
        for label, doc in (("as published", self.source), ("with inherents + incarnates",
                                                          self.rich_source())):
            with self.subTest(label):
                first = self.imported(doc)
                exported = self.export(first)["skif"]
                text = dump_document(exported)            # our codec accepts it
                again = self.imported(load_document(text))
                self.assertEqual(again, first)

    def test_pool_and_renamed_epic_round_trip_under_sidekicks_ids(self):
        doc = copy.deepcopy(self.source)
        doc["build"]["pools"] = [{"id": "leaping", "powers": [
            {"internalName": "Combat_Jumping", "level": 4, "slots": [None]}]}]
        doc["build"]["epicPool"] = {"id": "melee_psionic_mastery", "powers": [
            {"internalName": "Mental_Blast", "level": 35, "slots": [None]}]}
        first = self.imported(doc)
        self.assertEqual(first["epic"], "Epic.Psionic_Mastery_ScrapStalk")
        exported = self.export(first)["skif"]
        self.assertEqual(exported["build"]["epicPool"]["id"], "melee_psionic_mastery")
        self.assertEqual([p["id"] for p in exported["build"]["pools"]], ["leaping"])
        self.assertEqual(self.imported(exported), first)

    def sample(self, name):
        from export_skif_samples import UPSTREAM, v5_from_v4
        self.assertEqual(UPSTREAM, self.checkout)
        return v5_from_v4(name)

    def test_kheldian_and_arachnos_builds_round_trip(self):
        for name in ("homecoming-kheldian", "homcoming-level-up-arachnos"):
            with self.subTest(name):
                first = self.imported(self.sample(name))
                exported = self.export(first)["skif"]
                self.assertEqual(self.imported(load_document(dump_document(exported))), first)

    def test_dsync_exports_under_sidekicks_spelling_and_round_trips(self):
        first = self.imported(self.sample("sojourner_1784025393210"))
        exported = self.export(first)["skif"]
        self.assertEqual(self.imported(exported), first)
        slots = [s for sel in ("primary", "secondary") for p in exported["build"][sel]["powers"]
                 for s in p["slots"] if s and s["type"] == "special"]
        self.assertIn({"type": "special", "category": "d-sync", "id": "empowerment"},
                      [{k: s[k] for k in ("type", "category", "id")} for s in slots])

    def with_slot_order(self, name):
        doc = self.sample(name)
        doc["build"]["slotOrder"] = json.loads(
            (self.checkout / f"fixtures/skif/v4/{name}.skif").read_text(encoding="utf-8")
        )["build"]["slotOrder"]
        return doc

    def test_unchanged_slots_export_sidekicks_slot_history_verbatim(self):
        doc = self.with_slot_order("homecoming-troller")
        first = self.imported(doc)
        result = self.export(first)
        self.assertFalse(result["dropped_slot_order"])
        self.assertEqual(result["skif"]["build"]["slotOrder"], doc["build"]["slotOrder"])
        self.assertEqual(self.imported(load_document(dump_document(result["skif"]))), first)

    def test_changed_slots_leave_the_slot_history_out_and_say_so(self):
        for change in ("add a slot", "move a pick"):
            with self.subTest(change):
                build = self.imported(self.with_slot_order("homecoming-troller"))
                power = next(p for p in build["powers"] if len(p["slots"]) < 6
                             and not p["full_name"].startswith("Inherent."))
                if change == "add a slot":
                    power["slots"].append(None)
                else:
                    power["pick_level"] += 1
                result = self.export(build)
                self.assertTrue(result["dropped_slot_order"])
                self.assertNotIn("slotOrder", result["skif"]["build"])

    def test_a_build_without_slot_history_drops_nothing(self):
        result = self.export(self.imported(self.source))
        self.assertFalse(result["dropped_slot_order"])
        self.assertNotIn("slotOrder", result["skif"]["build"])

    def test_accolades_export_as_sidekick_stores_them_and_round_trip(self):
        doc = self.sample("homcoming-level-up-arachnos")
        doc["build"]["accolades"] = ["the_atlas_medallion", "portal_jockey"]
        first = self.imported(doc)
        exported = self.export(first)["skif"]
        self.assertEqual(exported["build"]["accolades"], ["the_atlas_medallion", "portal_jockey"])
        self.assertEqual(self.imported(load_document(dump_document(exported))), first)

    def test_a_repeated_accolade_is_written_once(self):
        build = self.imported(self.source)
        build["accolades"] = ["Portal_Jockey", "portal_jockey"]
        exported = self.export(build)["skif"]
        self.assertEqual(exported["build"]["accolades"], ["portal_jockey"])
        self.assertEqual(self.imported(exported)["accolades"], ["Portal_Jockey"])

    def test_an_accolade_sidekick_lacks_refuses_the_export(self):
        build = self.imported(self.source)
        build["accolades"] = ["Not_An_Accolade"]
        result = self.export_direct(build)
        self.assertFalse(result["ok"])
        self.assertIn("accolade_not_exportable", [i["reason"] for i in result["issues"]])

    def test_kheldian_form_attacks_export_inside_their_powerset(self):
        exported = self.export(self.imported(self.sample("homecoming-kheldian")))["skif"]["build"]
        self.assertIn("Bright_Nova_Bolt",
                      [p["internalName"] for p in exported["primary"]["powers"]])
        self.assertNotIn("inherents", exported)

    def test_arachnos_export_names_the_base_set_and_each_branch_pick(self):
        exported = self.export(self.imported(
            self.sample("homcoming-level-up-arachnos")))["skif"]["build"]
        self.assertEqual(exported["primary"]["id"], "arachnos-soldier/arachnos-soldier")
        sets = {p["internalName"]: p.get("powerset") for p in exported["primary"]["powers"]}
        self.assertEqual(sets["Longfang"], "arachnos-soldier/crab-spider-soldier")
        self.assertIsNone(sets["Single_Shot"])

    def test_export_writes_sidekicks_own_identities(self):
        doc = self.rich_source()
        exported = self.export(self.imported(doc))["skif"]["build"]
        original = doc["build"]
        self.assertEqual(exported["archetype"], original["archetype"])
        for bucket in ("primary", "secondary"):
            self.assertEqual(exported[bucket]["id"], original[bucket]["id"])
            self.assertEqual([(p["internalName"], p["level"]) for p in exported[bucket]["powers"]],
                             [(p["internalName"], p["level"]) for p in original[bucket]["powers"]])
        self.assertEqual(sorted(p["internalName"] for p in exported["inherents"]),
                         sorted(p["internalName"] for p in original["inherents"]))
        self.assertEqual(exported["incarnates"], original["incarnates"])
        self.assertEqual(exported["attackChains"], original["attackChains"])

    def test_solver_placed_attuned_pieces_export_as_attuned(self):
        # The solver places attuned/superior pieces by uid alone, with no
        # "attuned" flag (same rule as mids_import: the uid says it).
        build = self.imported(self.source)
        build["powers"][0]["slots"] = [
            {"piece_uid": "Attuned_Overwhelming_Force_F", "set_uid": "Overwhelming Force"},
            {"piece_uid": "Superior_Attuned_Avalanche_A"}]
        slots = self.export(build)["skif"]["build"]["primary"]["powers"][0]["slots"]
        self.assertEqual([(s["setId"], s["pieceNum"], s["attuned"]) for s in slots],
                         [("overwhelming_force", 6, True), ("superior_avalanche", 1, True)])

    def test_bridged_pieces_export_under_the_games_uid_and_round_trip(self):
        # Ours: Crafted_Shrapnel_A (Artillery) and an attuned Crafted_Apocalypse_A.
        # The game's: Crafted_Artillery_A and Superior_Attuned_Apocalypse_A.
        build = self.imported(self.source)
        build["powers"][0]["slots"] = [
            {"piece_uid": "Crafted_Shrapnel_A", "set_uid": "Artillery", "io_level": 50},
            {"piece_uid": "Crafted_Apocalypse_A", "set_uid": "Apocalypse", "attuned": True}]
        exported = self.export(build)["skif"]
        slots = exported["build"]["primary"]["powers"][0]["slots"]
        self.assertEqual([(s["setId"], s["pieceNum"], s["attuned"]) for s in slots],
                         [("artillery", 1, False), ("apocalypse", 1, True)])
        again = self.imported(exported)["powers"][0]["slots"]
        self.assertEqual([(s["piece_uid"], s["attuned"]) for s in again],
                         [("Crafted_Shrapnel_A", False), ("Crafted_Apocalypse_A", True)])

    def test_character_level_survives_both_directions(self):
        # The app keeps the character's level as level_reached; a level-32
        # Sidekick character must not come back as level 50.
        doc = copy.deepcopy(self.source)
        doc["build"]["level"] = 32
        build = self.imported(doc)
        self.assertEqual(build["level_reached"], 32)
        app_shape = {k: v for k, v in build.items() if k != "char_level"}
        self.assertEqual(self.export(app_shape)["skif"]["build"]["level"], 32)

    def test_unslotted_inherents_are_not_written(self):
        build = self.imported(self.source)
        build["powers"].append({"full_name": "Inherent.Fitness.Swift", "slots": [None],
                                "slotCount": 1, "powerset_full_name": "Inherent.Fitness"})
        exported = self.export(build)["skif"]["build"]
        self.assertNotIn("inherents", exported)

    def test_anything_without_a_sidekick_identity_refuses_the_export(self):
        build = self.imported(self.source)
        build["powers"][0]["slots"].append({"piece_uid": "Not_A_Real_Piece", "set_uid": None})
        result = export_build(build, self.hero, self.contract)
        self.assertFalse(result["ok"])
        self.assertNotIn("skif", result)
        self.assertIn("enhancement_not_exportable", [i["reason"] for i in result["issues"]])

    def test_unsupported_native_inherent_is_not_silently_dropped(self):
        # The importer cannot represent nonstandard inherited powers, and
        # the exporter must not claim success while discarding a selected one.
        build = self.imported(self.source)
        build["powers"].append({
            "full_name": "Inherent.Archetype_Only.Example_Power",
            "powerset_full_name": "Inherent.Archetype_Only",
            "slots": [None], "slotCount": 1})
        result = export_build(build, self.hero, self.contract, self.hero_sets,
                              hero_piece_by_uid=self.pieces)
        self.assertFalse(result["ok"])
        self.assertNotIn("skif", result)
        self.assertIn("inherent_not_exportable", [i["reason"] for i in result["issues"]])

    def test_unknown_incarnate_identity_does_not_generate_unreadable_skif(self):
        # The SKIF JSON codec checks shape, not whether a source dataset
        # actually contains the requested incarnate power.
        build = self.imported(self.source)
        build["incarnates"] = {"Alpha": {
            "full_name": "Incarnate.Alpha.This_Power_Does_Not_Exist",
            "display_name": "Imaginary Alpha", "active": True}}
        result = export_build(build, self.hero, self.contract, self.hero_sets,
                              hero_piece_by_uid=self.pieces)
        self.assertFalse(result["ok"])
        self.assertNotIn("skif", result)
        self.assertIn("incarnate_not_exportable", [i["reason"] for i in result["issues"]])

    def test_case_different_duplicate_incarnates_do_not_overwrite_each_other(self):
        build = self.imported(self.source)
        build["incarnates"] = {
            "Alpha": {"full_name": "Incarnate.Alpha.Agility_Core_Paragon", "active": True},
            "alpha": {"full_name": "Incarnate.Alpha.Agility_Boost", "active": False},
        }
        result = self.export_direct(build)
        self.assertFalse(result["ok"])
        self.assertNotIn("skif", result)
        self.assertIn("incarnate_not_exportable", [i["reason"] for i in result["issues"]])

    def export_direct(self, build):
        return export_build(build, self.hero, self.contract, self.hero_sets,
                            hero_piece_by_uid=self.pieces)

    def test_stale_attack_chain_is_reported_not_silently_dropped(self):
        build = self.imported(self.source)
        removed = build["sidekick_attack_chains"][0]["powers"][0]
        build["powers"] = [p for p in build["powers"] if p["full_name"] != removed]
        result = export_build(build, self.hero, self.contract)
        self.assertTrue(result["ok"], result["issues"])
        self.assertTrue(result["dropped"])
        self.assertTrue(all(removed not in json.dumps(c) for c in
                            result["skif"]["build"].get("attackChains", [])))


if __name__ == "__main__":
    unittest.main()
