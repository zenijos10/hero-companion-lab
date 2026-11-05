"""Where the Sidekick ID map comes from: one swappable provider list.

No network: every download goes through a fake fetcher. The real pinned
bundle is checked separately in test_sidekick_contract_sidekick.py (CI).
"""
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import sidekick_contract as sc
from sidekick_preview import preview_build


def bundle(**overrides):
    data = {
        "manifest": {"dataset": "homecoming", "shards": [
            {"id": "blaster/dual-pistols",
             "path": "powersets/blaster/primary/dual-pistols.json"}]},
        "powersets": {"blaster/dual-pistols": {
            "id": "blaster/dual-pistols", "setPath": "Blaster_Ranged.Dual_Pistols",
            "archetype": "blaster", "category": "primary", "name": "Dual Pistols",
            "description": "not needed by the importer",
            "powers": [{"internalName": "Pistols", "effects": ["large"]}]}},
        "archetypes": {"archetypes": {"blaster": {"stats": {"className": "Class_Blaster"}}}},
        "boost-index": {"Crafted_Recharge": {"kind": "common-io", "level": None,
                                             "stats": ["Recharge"]}},
        "enhancements": {"commonIoTypes": ["Recharge"], "hamidon": []},
        "mids-names": {"nameMap": {}, "nameReverse": {}},
        "levels": {
            "INHERENT_FITNESS_POWERS": [{"internalName": "Health",
                                         "fullName": "Inherent.Fitness.Health",
                                         "description": "not needed"}],
            "BASIC_INHERENT_POWERS": [], "PRESTIGE_SPRINT_POWERS": [],
            "SLOT_GRANTS": {"3": 2}},
        "io-sets": {"unused": "by the importer"},
    }
    data.update(overrides)
    return gzip.compress(json.dumps(data).encode("utf-8"))


def snapshot_for(raw, **extra):
    return sc.Snapshot(version="test-1", url="https://example.invalid/bundle.json.gz",
                       sha256=hashlib.sha256(raw).hexdigest(), **extra)


class FakeFetch:
    def __init__(self, raw):
        self.raw, self.calls = raw, []

    def __call__(self, url, max_bytes):
        self.calls.append((url, max_bytes))
        return self.raw


class ProviderChoiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "cache"

    def test_configured_folder_outranks_the_download(self):
        folder = self.cache.parent / "mine"
        folder.mkdir()
        providers = [sc.ConfiguredFolder({"HC_SIDEKICK_CONTRACT_DIR": str(folder)}),
                     sc.DownloadedSnapshot(self.cache, snapshot_for(b""))]
        self.assertEqual(sc.locate_contract(providers), (folder, "configured-folder"))

    def test_nothing_available_names_the_provider_that_can_install(self):
        download = sc.DownloadedSnapshot(self.cache, snapshot_for(b""))
        providers = [sc.ConfiguredFolder({"HC_SIDEKICK_CONTRACT_DIR": "/no/such/dir"}), download]
        self.assertEqual(sc.locate_contract(providers), (None, None))
        self.assertIs(sc.installer(providers), download)

    def test_a_new_strategy_is_just_another_provider(self):
        class Elsewhere:
            name = "elsewhere"

            def locate(self):
                return Path("/somewhere")
        self.assertEqual(sc.locate_contract([Elsewhere()]), (Path("/somewhere"), "elsewhere"))
        self.assertIsNone(sc.installer([Elsewhere()]))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "cache"

    def install(self, raw, snapshot=None):
        fetch = FakeFetch(raw)
        provider = sc.DownloadedSnapshot(self.cache, snapshot or snapshot_for(raw), fetch=fetch)
        return provider, fetch, provider.install()

    def assert_nothing_installed(self):
        leftovers = list(self.cache.iterdir()) if self.cache.exists() else []
        self.assertEqual(leftovers, [])

    def test_inherent_name_table_installs_slim_and_is_required(self):
        provider, _, root = self.install(bundle())
        self.assertEqual(json.loads((root / "levels.json").read_text()), {
            "INHERENT_FITNESS_POWERS": [{"internalName": "Health",
                                         "fullName": "Inherent.Fitness.Health"}],
            "BASIC_INHERENT_POWERS": [], "PRESTIGE_SPRINT_POWERS": []})
        # A cache from before the table existed is incomplete, so it re-installs.
        (root / "levels.json").unlink()
        self.assertIsNone(provider.locate())

    def test_verified_bundle_installs_the_slim_contract_layout(self):
        provider, fetch, root = self.install(bundle())
        self.assertEqual(provider.locate(), root)
        self.assertEqual(fetch.calls[0][1], sc.MAX_DOWNLOAD_BYTES)
        for name in ("manifest.json", "archetypes.json", "boost-index.json",
                     "enhancements.json", "mids-names.json"):
            self.assertTrue((root / name).is_file(), name)
        shard = json.loads((root / "powersets/blaster/primary/dual-pistols.json").read_text())
        self.assertEqual(shard, {"id": "blaster/dual-pistols",
                                 "setPath": "Blaster_Ranged.Dual_Pistols",
                                 "archetype": "blaster", "category": "primary",
                                 "powers": [{"internalName": "Pistols"}]})

    def test_second_install_reuses_the_cache(self):
        provider, fetch, root = self.install(bundle())
        self.assertEqual(provider.install(), root)
        self.assertEqual(len(fetch.calls), 1)

    def test_wrong_checksum_installs_nothing(self):
        raw = bundle()
        with self.assertRaises(sc.ContractUnavailable):
            self.install(raw, snapshot_for(b"other bytes"))
        self.assert_nothing_installed()

    def test_oversize_or_corrupt_download_installs_nothing(self):
        raw = bundle()
        with self.assertRaises(sc.ContractUnavailable):
            self.install(raw, snapshot_for(raw, max_bytes=len(raw) - 1))
        corrupt = b"not gzip"
        with self.assertRaises(sc.ContractUnavailable):
            self.install(corrupt)
        self.assert_nothing_installed()

    def test_unsafe_or_foreign_bundle_installs_nothing(self):
        escape = bundle(manifest={"dataset": "homecoming", "shards": [
            {"id": "blaster/dual-pistols", "path": "../../outside.json"}]})
        rebirth = bundle(manifest={"dataset": "rebirth", "shards": []})
        missing = bundle(powersets={})
        for raw in (escape, rebirth, missing):
            with self.subTest(raw=raw[:12]), self.assertRaises(sc.ContractUnavailable):
                self.install(raw)
        self.assert_nothing_installed()

    def test_missing_cache_member_is_not_accepted_and_is_repaired(self):
        provider, fetch, root = self.install(bundle())
        (root / "boost-index.json").unlink()
        self.assertIsNone(provider.locate(), "A manifest alone is not a valid contract")
        repaired = provider.install()
        self.assertEqual(repaired, root)
        self.assertTrue((root / "boost-index.json").is_file())
        self.assertEqual(len(fetch.calls), 2)
        self.assertFalse(any(p.name.startswith(".staging-")
                             for p in self.cache.iterdir()))

    def test_damaged_json_cache_is_rejected_and_healed(self):
        for filename in ("boost-index.json", "powersets/blaster/primary/dual-pistols.json"):
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmp:
                    cache = Path(tmp)
                    raw = bundle()
                    fetch = FakeFetch(raw)
                    provider = sc.DownloadedSnapshot(cache, snapshot_for(raw), fetch=fetch)
                    root = provider.install()
                    (root / filename).write_text("{ broken JSON", encoding="utf-8")
                    self.assertIsNone(provider.locate())
                    self.assertEqual(provider.install(), root)
                    self.assertEqual(len(fetch.calls), 2)

    def test_simultaneous_install_returns_the_healthy_winner(self):
        raw = bundle()
        pin = snapshot_for(raw)
        peer = sc.DownloadedSnapshot(self.cache, pin, fetch=FakeFetch(raw))

        def interleaved_fetch(url, max_bytes):
            # The other request finishes after this one checked locate()
            # but before this one attempts to publish its staging folder.
            peer.install()
            return raw

        participant = sc.DownloadedSnapshot(self.cache, pin, fetch=interleaved_fetch)
        result = participant.install()
        self.assertEqual(result, peer.locate())
        self.assertTrue((result / "boost-index.json").is_file())
        self.assertFalse(any(p.name.startswith(".staging-")
                             for p in self.cache.iterdir()))

    def test_malformed_shard_is_a_clean_refusal(self):
        bad = bundle(powersets={"blaster/dual-pistols": {
            "id": "blaster/dual-pistols", "setPath": "Blaster_Ranged.Dual_Pistols",
            "archetype": "blaster", "category": "primary",
            "powers": "not an array"}})
        with self.assertRaises(sc.ContractUnavailable):
            self.install(bad)
        self.assert_nothing_installed()

    def test_installed_contract_drives_the_existing_preview(self):
        _, _, root = self.install(bundle())
        doc = {"version": 5, "build": {
            "dataset": "homecoming", "archetype": "blaster", "level": 50,
            "primary": {"id": "blaster/dual-pistols", "powers": [
                {"internalName": "Pistols", "level": 1, "slots": [None]}]}}}
        hero = {"Blaster_Ranged.Dual_Pistols.Pistols": {"display_name": "Pistols"}}
        result = preview_build(doc, hero, root)
        self.assertEqual(result["resolved"][0]["hero_power"], "Blaster_Ranged.Dual_Pistols.Pistols")
        self.assertEqual(result["unresolved"], [])


if __name__ == "__main__":
    unittest.main()
