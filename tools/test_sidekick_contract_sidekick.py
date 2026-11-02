"""The pinned Sidekick bundle is exactly what the app downloads, and it imports
the same build as Sidekick's full contract folder.

Requires the sparse upstream checkout in _sidekick_contract_fixture (CI job).
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
import sidekick_contract as sc
from preview_skif import _enhancement_lookups
from sidekick_reconstruct import reconstruct_build


class PinnedSidekickBundleTests(unittest.TestCase):
    def setUp(self):
        self.upstream = ROOT / "_sidekick_contract_fixture"
        self.full = self.upstream / "contract/homecoming"
        self.raw = (self.full / "bundle.json.gz").read_bytes()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name)

    def test_pinned_checksum_matches_the_published_bundle(self):
        self.assertTrue(sc.SIDEKICK_SNAPSHOT.url.split("/")[5] == sc.SIDEKICK_SNAPSHOT.version)
        provider = sc.DownloadedSnapshot(self.cache, sc.SIDEKICK_SNAPSHOT,
                                         fetch=lambda url, limit: self.raw)
        self.assertTrue((provider.install() / "manifest.json").is_file())

    def test_slim_download_imports_exactly_like_the_full_contract(self):
        provider = sc.DownloadedSnapshot(self.cache, sc.SIDEKICK_SNAPSHOT,
                                         fetch=lambda url, limit: self.raw)
        slim = provider.install()
        source = json.loads((self.upstream / "fixtures/skif/v5/rb5d_browser_pass.skif")
                            .read_text(encoding="utf-8"))
        supported = copy.deepcopy(source)
        supported["build"].pop("attackChains")
        powers = json.loads((ROOT / "data/powers.json").read_text(encoding="utf-8"))
        by_full = {p["full_name"]: p for group in powers.values() for p in group}
        powersets = json.loads((ROOT / "data/powersets.json").read_text(encoding="utf-8"))
        catalog = _enhancement_lookups()
        for document in (source, supported):
            with self.subTest(attack_chains="attackChains" in document["build"]):
                from_full = reconstruct_build(document, by_full, powersets, self.full, catalog)
                from_slim = reconstruct_build(document, by_full, powersets, slim, catalog)
                self.assertEqual(from_slim["ok"], from_full["ok"])
                self.assertEqual(from_slim["issues"], from_full["issues"])
                self.assertEqual(from_slim.get("build"), from_full.get("build"))
        self.assertTrue(reconstruct_build(supported, by_full, powersets, slim, catalog)["ok"])


if __name__ == "__main__":
    unittest.main()
