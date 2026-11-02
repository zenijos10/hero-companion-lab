"""Flask endpoint smoke: Sidekick must pass actual HC import and legality gates.

Uses Sidekick's pinned external Homecoming fixture in CI; no saves are written.
"""
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "ai")]
import server as app_server


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

    def send(self, source, *, configured=True, **extra):
        config = {"HC_SIDEKICK_CONTRACT_DIR": str(self.contract_root) if configured else ""}
        with patch.dict(os.environ, config):
            response = self.client.post("/build/import-sidekick",
                                        json={"skif": json.dumps(source), **extra})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_without_external_contract_never_returns_a_build(self):
        response = self.send(self.source, configured=False)
        self.assertFalse(response["ok"])
        self.assertEqual(response["code"], "sidekick_contract_unavailable")
        self.assertNotIn("build", response)

    def test_unsupported_attack_chain_refuses_without_a_partial_build(self):
        response = self.send(self.source)
        self.assertFalse(response["ok"])
        self.assertEqual(response["code"], "sidekick_unresolved")
        self.assertNotIn("build", response)
        self.assertTrue(any(x["location"] == "build.attackChains"
                            for x in response["issues"]))

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

    def test_client_cannot_override_contract_directory(self):
        supported = copy.deepcopy(self.source)
        supported["build"].pop("attackChains")
        response = self.send(supported, contract_root="/nonexistent/elsewhere", pvp=False)
        self.assertTrue(response["ok"], response.get("response"))


if __name__ == "__main__":
    unittest.main()
