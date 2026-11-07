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


# The Arachnos sample's accolades as Sidekick's current reader stores them.
ACCOLADES_IN_SAMPLE = ["the_atlas_medallion", "freedom_phalanx_reserve",
                       "task_force_commander", "portal_jockey"]

# The sample's secondary picks that live in the Crab Spider training branch.
CRAB_TRAINING_PICKS = ("Crab_Spider_Armor", "Fortification", "Serum", "Summon_Spiderlings")


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
        from export_skif_samples import v5_from_v4
        return v5_from_v4(name, buckets)

    def test_every_sidekick_set_piece_resolves_to_one_of_ours(self):
        # Coverage over Sidekick's WHOLE io-set catalog, not one sample. Before
        # the set/piece-number bridge, 72 of these refused: Artillery (our
        # Crafted_Shrapnel_*) and attuned purples (Superior_Attuned_Apocalypse_A).
        import re
        from sidekick_enhancements import EnhancementResolver
        bridge = EnhancementResolver(self.contract, self.enhancements)
        boosts = json.loads((self.contract / "boost-index.json").read_text(encoding="utf-8"))
        io_sets = json.loads((self.contract / "io-sets.json").read_text(encoding="utf-8"))

        def words(name):   # the two catalogs word the same piece differently
            name = re.sub(r"chance (for|of)|duration|reduction|\(|\)|\s|/", " ", name.casefold())
            return set(name.replace("tohit", "to hit").replace("confused", "confuse").split())
        records = [(u, r) for u, r in boosts.items() if r.get("kind") == "io-set"]
        unresolved, disagree, bridged = [], [], []
        for uid, record in records:
            mapped, issue = bridge.resolve({"type": "io-set", "setId": record["set"],
                                            "pieceNum": record["piece"],
                                            "attuned": record["attuned"], "level": 50})
            if issue:
                unresolved.append((uid, issue))
                continue
            if uid in self.enhancements:
                continue                    # matched by exact uid: identity is the proof
            bridged.append(uid)
            ours = next((p for p in self.pieces_by_uid().get(mapped["hero_slot"]["piece_uid"], [])), None)
            theirs = io_sets[record["set"]]["pieces"][record["piece"] - 1]["name"]
            if ours is not None and not (words(ours) & words(theirs)):
                disagree.append((uid, ours, theirs))
        self.assertEqual((len(records), unresolved), (2078, []))
        self.assertEqual(len(bridged), 72)      # Artillery + attuned purples
        self.assertEqual(disagree, [])          # and each bridged name agrees

    @classmethod
    def pieces_by_uid(cls):
        sets = json.loads((ROOT / "data/enhancement_sets.json").read_text(encoding="utf-8"))
        return {p["uid"]: [p["name"]] for s in sets for p in s["pieces"] if p.get("uid")}

    def test_every_sidekick_special_we_have_resolves(self):
        # Sidekick writes DSync_*, we write Dsync_*: the same uid but for case.
        # The Synthetic Hamidon and Generic_* specials are not in our data at
        # all; they stay refused, named here so a data change shows up.
        from sidekick_enhancements import EnhancementResolver
        bridge = EnhancementResolver(self.contract, self.enhancements)
        boosts = json.loads((self.contract / "boost-index.json").read_text(encoding="utf-8"))
        specials = {u: r for u, r in boosts.items() if r.get("kind") == "special"}
        missing = sorted(u for u, r in specials.items() if bridge.resolve(
            {"type": "special", "category": r["family"], "id": r["id"]})[1])
        self.assertEqual(len(specials), 78, "denominator: Sidekick's special enhancements")
        self.assertEqual(missing, sorted(
            [f"Synthetic_Hamidon_{s}" for s in (
                "Accuracy_Mez", "Buff_Endurance_Discount", "Buff_Recharge", "Damage_Accuracy",
                "Damage_Mez", "Damage_Range", "DeBuff_Accuracy", "DeBuff_Endurance_Discount",
                "Heal_Endurance_Discount", "Res_Damage_Endurance_Discount",
                "Travel_Endurance_Discount")]
            + [f"Generic_{s}" for s in ("Clockwork_Efficiency", "Might_of_the_Empire",
                                        "Resistance_Tactics", "Syndicate_Techniques",
                                        "Will_of_the_Seers")]))

    def test_sojourner_sample_with_a_dsync_imports_whole(self):
        converted = self.reconstruct(self.v5_from_v4("sojourner_1784025393210"))
        self.assertTrue(converted["ok"], converted["issues"][:5])
        fire_ball = next(p for p in converted["build"]["powers"]
                         if p["full_name"].endswith(".Fire_Ball"))
        self.assertEqual(fire_ball["slots"][5]["piece_uid"], "Dsync_Damage_Accuracy")

    def test_every_real_sample_imports_whole_with_its_slot_history(self):
        from export_skif_samples import UPSTREAM
        for name in ("controller_import_1785756407256", "homcoming-level-up-arachnos",
                     "homecoming-kheldian", "homecoming-troller", "proc test",
                     "sojourner_1784025393210"):
            with self.subTest(name):
                doc = self.v5_from_v4(name)
                order = json.loads((UPSTREAM / f"fixtures/skif/v4/{name}.skif")
                                   .read_text(encoding="utf-8"))["build"]["slotOrder"]
                doc["build"]["slotOrder"] = order
                converted = self.reconstruct(doc)
                self.assertTrue(converted["ok"], converted["issues"][:5])
                kept = converted["build"]["sidekick_slot_order"]
                self.assertEqual(kept["entries"], order)      # verbatim, never interpreted
                self.assertTrue(kept["shape"])

    def test_the_arachnos_samples_accolades_land_on_our_accolade_keys(self):
        doc = self.v5_from_v4("homcoming-level-up-arachnos")
        doc["build"]["accolades"] = ACCOLADES_IN_SAMPLE
        converted = self.reconstruct(doc)
        self.assertTrue(converted["ok"], converted["issues"][:5])
        self.assertEqual(converted["build"]["accolades"], [
            "The_Atlas_Medallion", "Freedom_Phalanx_Reserve", "Task_Force_Commander",
            "Portal_Jockey"])

    def test_every_sidekick_accolade_has_one_of_ours(self):
        from sidekick_preview import SourceSets
        ours = json.loads((ROOT / "data/accolades.json").read_text(encoding="utf-8"))
        shard = SourceSets(self.contract).get("Accolades")
        names = [p["internalName"] for p in shard["powers"]]
        self.assertEqual(len(names), 28, "denominator: Sidekick's accolade records")
        doc = self.v5_from_v4("homecoming-troller")
        doc["build"]["accolades"] = [n.lower() for n in names]   # Sidekick stores them folded
        converted = self.reconstruct(doc)
        self.assertTrue(converted["ok"], converted["issues"][:5])
        self.assertEqual(converted["build"]["accolades"], names)
        self.assertLessEqual(set(names), set(ours))

    def test_an_unknown_or_repeated_accolade_is_refused(self):
        for accolades, reason in ((["not_an_accolade"], "unknown_accolade"),
                                  (["portal_jockey", "Portal_Jockey"], "duplicate_accolade")):
            with self.subTest(reason):
                doc = self.v5_from_v4("homecoming-troller")
                doc["build"]["accolades"] = accolades
                converted = self.reconstruct(doc)
                self.assertFalse(converted["ok"])
                self.assertIn(reason, [i["reason"] for i in converted["issues"]])

    def proc_sample(self):
        from export_skif_samples import proc_settings_sample
        return proc_settings_sample()

    def test_proc_settings_pass_through_with_their_slot_anchors(self):
        converted = self.reconstruct(self.proc_sample())
        self.assertTrue(converted["ok"], converted["issues"][:5])
        kept = converted["build"]["sidekick_proc_settings"]
        self.assertEqual(kept["overrides"], self.proc_sample()["build"]["procOverrides"])
        self.assertEqual(kept["disabled_categories"], ["Defense"])
        self.assertEqual(kept["anchors"]["scrapper/energy-aura:Kinetic_Shield:0"],
                         ["Scrapper_Defense.Energy_Aura.Kinetic_Shield", 0,
                          "Crafted_Reactive_Defenses_F"])

    def test_an_override_naming_no_pick_is_kept_without_an_anchor(self):
        # Sidekick keeps orphans after a respec; they are no-ops there too.
        doc = self.proc_sample()
        doc["build"]["procOverrides"]["scrapper/energy-aura:Not_A_Power:0"] = {
            "enabled": False, "mode": "auto"}
        converted = self.reconstruct(doc)
        self.assertTrue(converted["ok"], converted["issues"][:5])
        kept = converted["build"]["sidekick_proc_settings"]
        self.assertIn("scrapper/energy-aura:Not_A_Power:0", kept["overrides"])
        self.assertNotIn("scrapper/energy-aura:Not_A_Power:0", kept["anchors"])

    def test_an_override_on_an_inherent_is_anchored(self):
        # Health's Miracle in this sample; Sidekick addresses inherents "Inherent:<name>".
        doc = self.proc_sample()
        doc["build"]["procOverrides"]["Inherent:Health:0"] = {"enabled": False, "mode": "auto"}
        kept = self.reconstruct(doc)["build"]["sidekick_proc_settings"]
        self.assertEqual(kept["anchors"]["Inherent:Health:0"][:2], ["Inherent.Fitness.Health", 0])
        self.assertIsNotNone(kept["anchors"]["Inherent:Health:0"][2])

    def test_sidekicks_on_off_switch_becomes_our_count_in_totals_checkbox(self):
        # Sidekick's math: an Auto power always counts; a toggle or click counts
        # only when switched on (coh_math gather.rs). Ours: include_in_totals.
        from export_skif_samples import UPSTREAM
        for name in ("homecoming-troller", "controller_import_1785756407256",
                     "homecoming-kheldian", "homcoming-level-up-arachnos"):
            with self.subTest(name):
                doc = self.v5_from_v4(name)
                build = self.reconstruct(doc)["build"]
                switched = {p["internalName"].casefold(): bool(p.get("isActive"))
                            for b in ("primary", "secondary") for p in doc["build"][b]["powers"]}
                checked = 0
                for power in build["powers"]:
                    leaf = power["full_name"].rsplit(".", 1)[-1].casefold()
                    if leaf not in switched or power["full_name"].startswith("Inherent."):
                        continue
                    if power["power_type"] == 1:        # Auto: always counted
                        self.assertNotIn("include_in_totals", power)
                    else:
                        self.assertEqual(power["include_in_totals"], switched[leaf], leaf)
                        checked += 1
                self.assertGreater(checked, 5)

    def test_sidekicks_homecoming_controller_with_four_pools_imports_whole(self):
        doc = self.v5_from_v4("homecoming-troller")   # its Artillery slots included
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

    def test_kheldian_and_arachnos_samples_import_whole(self):
        # Sidekick files the Kheldian and Arachnos (VEAT) primaries and
        # secondaries under the "epic" category, the game's own grouping.
        for name, at in (("homecoming-kheldian", "Class_Peacebringer"),
                         ("homcoming-level-up-arachnos", "Class_Arachnos_Soldier")):
            with self.subTest(name):
                converted = self.reconstruct(self.v5_from_v4(name))
                self.assertTrue(converted["ok"], converted["issues"][:5])
                self.assertEqual(converted["build"]["archetype"], at)

    def test_kheldian_form_attacks_land_on_our_granted_records(self):
        # Sidekick's own record: autoIssue + free, and its requires names
        # Inherent.Inherent.Bright_Nova_Bolt, the record we keep it under.
        build = self.reconstruct(self.v5_from_v4("homecoming-kheldian"))["build"]
        bolt = next(p for p in build["powers"]
                    if p["full_name"] == "Inherent.Inherent.Bright_Nova_Bolt")
        self.assertEqual((bolt["powerset_full_name"], bolt["pick_level"], len(bolt["slots"])),
                         ("Inherent.Inherent", 4, 6))
        self.assertEqual(build["primary"], "Peacebringer_Offensive.Luminous_Blast")

    def test_every_kheldian_and_arachnos_power_the_game_offers_resolves(self):
        # Coverage over all 16 sets Sidekick files under "epic" (the Kheldian
        # and Arachnos primaries/secondaries), not just the two samples.
        from sidekick_preview import SourceSets, _index_powers, _resolve_source_power
        sources = SourceSets(self.contract)
        index = _index_powers(self.hero)
        offered, unresolved = 0, []
        for set_id in sources.paths:
            shard = sources.get(set_id)
            if shard.get("category") != "epic":
                continue
            for record in shard["powers"]:
                if record.get("available", 0) < 0:
                    continue    # never offered (Quantum Boost: a sub-power, no slots)
                offered += 1
                if _resolve_source_power(record, shard, sources.mids, self.hero, index,
                                         set_id, [], None) is None:
                    unresolved.append((set_id, record["internalName"]))
        self.assertEqual(unresolved, [])
        self.assertEqual(offered, 166, "denominator: offered powers in the 16 sets")

    def test_kheldian_travel_inherent_imports_slotted(self):
        doc = self.v5_from_v4("homecoming-kheldian")
        doc["build"]["secondary"]["powers"].append(
            {"internalName": "Energy_Flight", "level": 1,
             "slots": [{"type": "io-generic", "stat": "EnduranceReduction", "level": 50}]})
        converted = self.reconstruct(doc)
        self.assertTrue(converted["ok"], converted["issues"][:5])
        self.assertIn("Inherent.Inherent.Energy_Flight",
                      [p["full_name"] for p in converted["build"]["powers"]])

    def veat_v5(self):
        # Sidekick's current writer: the selection names the BASE set, and a
        # branch pick names its own set.
        doc = self.v5_from_v4("homcoming-level-up-arachnos")
        for power in doc["build"]["primary"]["powers"]:
            if power["internalName"] in ("Longfang", "Aim", "Suppression", "Slice",
                                         "Frenzy", "Arm_Lash"):
                power["powerset"] = "arachnos-soldier/crab-spider-soldier"
        return doc

    def test_arachnos_branch_picks_seat_the_branch_and_keep_base_picks(self):
        for label, doc in (("current v5", self.veat_v5()),
                           ("older file, branch picks under the base set",
                            self.v5_from_v4("homcoming-level-up-arachnos"))):
            with self.subTest(label):
                converted = self.reconstruct(doc)
                self.assertTrue(converted["ok"], converted["issues"][:5])
                build = converted["build"]
                self.assertEqual(build["primary"], "Arachnos_Soldiers.Crab_Spider_Soldier")
                sets = {p["full_name"]: p["powerset_full_name"] for p in build["powers"]}
                self.assertEqual(sets["Arachnos_Soldiers.Crab_Spider_Soldier.Longfang"],
                                 "Arachnos_Soldiers.Crab_Spider_Soldier")
                self.assertEqual(sets["Arachnos_Soldiers.Arachnos_Soldier.Single_Shot"],
                                 "Arachnos_Soldiers.Arachnos_Soldier")

    def test_a_branch_pick_is_judged_by_its_own_records_io_rules(self):
        doc = self.veat_v5()
        longfang = next(p for p in doc["build"]["primary"]["powers"]
                        if p["internalName"] == "Longfang")
        longfang["slots"][0] = {"type": "io-generic", "stat": "Damage", "level": 50}
        converted = self.reconstruct(doc)
        self.assertTrue(converted["ok"], converted["issues"][:5])
        longfang["slots"][0]["stat"] = "Healing"
        refused = self.reconstruct(doc)
        self.assertIn("invalid_generic_enhancement", [i["reason"] for i in refused["issues"]])

    def test_picks_from_two_arachnos_branches_are_refused(self):
        doc = self.veat_v5()
        doc["build"]["primary"]["powers"].append({
            "internalName": "Mace_Beam", "level": 49, "slots": [None],
            "powerset": "arachnos-soldier/bane-spider-soldier"})
        converted = self.reconstruct(doc)
        self.assertFalse(converted["ok"])
        self.assertIn("mixed_branch_sets", [i["reason"] for i in converted["issues"]])

    def test_primary_and_secondary_from_different_branches_are_refused(self):
        # One branch choice at 24 sets both: Crab primary + Bane secondary is impossible.
        doc = self.veat_v5()
        secondary = doc["build"]["secondary"]
        secondary["powers"] = [p for p in secondary["powers"] if p["internalName"]
                               not in CRAB_TRAINING_PICKS]      # no Crab secondary picks left
        secondary["powers"].append({
            "internalName": "Surveillance", "level": 49, "slots": [None],
            "powerset": "arachnos-soldier/bane-spider-training"})
        converted = self.reconstruct(doc)
        self.assertFalse(converted["ok"])
        self.assertIn("mixed_branch_sets", [i["reason"] for i in converted["issues"]])

    def test_a_branch_of_another_bucket_stays_refused(self):
        doc = self.veat_v5()
        doc["build"]["primary"]["powers"][2]["powerset"] = "arachnos-soldier/crab-spider-training"
        converted = self.reconstruct(doc)
        self.assertFalse(converted["ok"])
        self.assertIn("cross_set_power_not_mapped", [i["reason"] for i in converted["issues"]])

    def test_an_epic_category_primary_of_another_archetype_is_refused(self):
        doc = self.v5_from_v4("homecoming-kheldian")
        doc["build"]["primary"]["id"] = "warshade/umbral-blast"
        converted = self.reconstruct(doc)
        self.assertFalse(converted["ok"])
        self.assertIn("source_archetype_mismatch", [i["reason"] for i in converted["issues"]])

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
