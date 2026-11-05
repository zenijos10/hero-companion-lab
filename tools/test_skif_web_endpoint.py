"""Flask endpoint smoke: Sidekick must pass actual HC import and legality gates.

Uses Sidekick's pinned external Homecoming fixture in CI; no saves are written.
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "ai")]
import server as app_server
import sidekick_contract


class SidekickFlaskEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract_root = (ROOT / "_sidekick_contract_fixture" / "contract/homecoming")
        fixture = (ROOT / "_sidekick_contract_fixture" /
                   "fixtures/skif/v5/rb5d_browser_pass.skif")
        if not fixture.is_file():
            raise AssertionError("Missing pinned Sidekick v5 fixture checkout")
        cls.source = json.loads(fixture.read_text(encoding="utf-8"))
        cls.client = app_server.app.test_client()

    def setUp(self):
        # An empty download cache per test: a real download on this machine
        # must never decide what these tests see.
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.cache = Path(cache.name)
        patcher = patch.object(app_server, "_sidekick_cache_dir", return_value=self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, source, *, configured=True, **extra):
        config = {"HC_SIDEKICK_CONTRACT_DIR": str(self.contract_root) if configured else ""}
        with patch.dict(os.environ, config):
            response = self.client.post("/build/import-sidekick",
                                        json={"skif": json.dumps(source), **extra})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def download(self, body):
        pinned = (ROOT / "_sidekick_contract_fixture/contract/homecoming/bundle.json.gz").read_bytes()
        with patch.object(sidekick_contract, "_https_fetch", lambda url, limit: pinned), \
                patch.dict(os.environ, {"HC_SIDEKICK_CONTRACT_DIR": ""}):
            response = self.client.post("/sidekick/data/download", json=body)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_unavailable_data_offers_the_one_time_download(self):
        response = self.send(self.source, configured=False)
        self.assertEqual(response["code"], "sidekick_contract_unavailable")
        self.assertTrue(response["can_download"])
        self.assertGreater(response["download_bytes"], 0)

    def test_download_needs_explicit_consent(self):
        response = self.download({})
        self.assertFalse(response["ok"])
        self.assertEqual(response["code"], "sidekick_download_needs_consent")
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_consented_download_makes_import_work_without_any_folder_setting(self):
        response = self.download({"consent": True})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["source"], "sidekick-download")
        supported = copy.deepcopy(self.source)
        supported["build"].pop("attackChains")
        imported = self.send(supported, configured=False, pvp=False)
        self.assertTrue(imported["ok"], imported.get("response"))
        self.assertEqual(len(imported["build"]["powers"]), 7)

    def test_without_external_contract_never_returns_a_build(self):
        response = self.send(self.source, configured=False)
        self.assertFalse(response["ok"])
        self.assertEqual(response["code"], "sidekick_contract_unavailable")
        self.assertNotIn("build", response)

    def test_real_attack_chains_import_without_being_used_for_simulation(self):
        response = self.send(self.source)
        self.assertTrue(response["ok"], response.get("response"))
        self.assertEqual(len(response["build"]["powers"]), 7)
        chains = response["build"]["sidekick_attack_chains"]
        self.assertEqual(len(chains), 5)
        self.assertEqual(chains[0]["name"], "S1 banked charge")
        self.assertEqual(chains[0]["source_powers"],
                         self.source["build"]["attackChains"][0]["powers"])
        self.assertIn("totals", response)
        self.assertNotIn("source_skif", response)

    def test_derived_supported_subset_reaches_same_import_response_as_mids(self):
        supported = copy.deepcopy(self.source)
        supported["build"].pop("attackChains")
        response = self.send(supported, pvp=False)
        self.assertTrue(response["ok"], response.get("response"))
        self.assertEqual(response["build"]["archetype"], "Class_Stalker")
        self.assertEqual(len(response["build"]["powers"]), 7)
        self.assertTrue(all("slots" in p for p in response["build"]["powers"]))
        self.assertIn("totals", response)
        self.assertIn("critique", response)
        self.assertNotIn("source_skif", response)
        self.assertNotIn("editor_imported", response)
        self.assertEqual(supported["build"]["primary"]["powers"][0]["slots"], [])

    def test_health_generic_io_rejects_recharge_but_accepts_healing(self):
        for stat, expect_ok in (("Recharge", False), ("Healing", True)):
            with self.subTest(stat=stat):
                doc = copy.deepcopy(self.source)
                doc["build"]["inherents"] = [
                    {"internalName": "Health", "level": 1,
                     "slots": [{"type": "io-generic", "stat": stat, "level": 50}]}]
                response = self.send(doc)
                self.assertEqual(response["ok"], expect_ok, response)
                if expect_ok:
                    health = next(p for p in response["build"]["powers"]
                                  if p["full_name"] == "Inherent.Fitness.Health")
                    self.assertEqual(health["slots"][0]["piece_uid"], "Crafted_Heal")
                else:
                    self.assertNotIn("build", response)
                    self.assertIn("invalid_generic_enhancement",
                                  [i["reason"] for i in response["issues"]])

    def test_over_six_inherent_slots_cannot_reach_editor(self):
        doc = copy.deepcopy(self.source)
        doc["build"]["inherents"] = [
            {"internalName": "Health", "level": 1, "slots": [None] * 7}]
        result = self.send(doc)
        self.assertFalse(result["ok"])
        self.assertNotIn("build", result)
        self.assertIn("too_many_power_slots",
                      [i["reason"] for i in result["issues"]])

    def test_imported_chains_survive_a_real_save_and_resume(self):
        imported = self.send(self.source)
        self.assertTrue(imported["ok"], imported.get("response"))
        chains = imported["build"]["sidekick_attack_chains"]
        with tempfile.TemporaryDirectory() as tmp, patch.object(
                app_server, "_saves_dir", return_value=tmp):
            saved = self.client.post("/saves", json={
                "name": "SKIF Chain test (isolated temp directory)",
                "build": imported["build"],
            }).get_json()
            self.assertTrue(saved["ok"], saved)
            resumed = self.client.get("/saves/" + saved["id"]).get_json()
            self.assertTrue(resumed["ok"], resumed)
        self.assertEqual(resumed["save"]["build"]["sidekick_attack_chains"], chains)
        self.assertEqual(len(chains), 5)

    def test_client_cannot_override_contract_directory(self):
        supported = copy.deepcopy(self.source)
        supported["build"].pop("attackChains")
        response = self.send(supported, contract_root="/nonexistent/elsewhere", pvp=False)
        self.assertTrue(response["ok"], response.get("response"))


class ValidateReadsGameRestrictionsTests(unittest.TestCase):
    """/build/validate must enforce exclusions on the payload the app sends.

    buildPayload() ships full_name/pick_level/slots only, never `excludes`;
    before the shared validator enriched from the game data, a mutually
    exclusive pair passed /build/validate from the real app.
    """

    def test_bare_app_payload_still_reports_mutually_exclusive_pair(self):
        first, second = next(
            (name, other) for name, record in app_server.POWER_BY_FULL.items()
            for other in (record.get("excludes") or []) if other in app_server.POWER_BY_FULL)
        bare = {"archetype": "Class_Arachnos_Soldier", "powers": [
            {"full_name": first, "pick_level": 1, "slots": []},
            {"full_name": second, "pick_level": 2, "slots": []}]}
        response = app_server.app.test_client().post("/build/validate", json=bare)
        errors = response.get_json()["errors"]
        self.assertTrue(any("mutually exclusive" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
