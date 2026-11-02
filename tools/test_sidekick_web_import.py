"""Guarded Sidekick editor import handshake; no source file or editor mutation."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from sidekick_web_import import prepare_sidekick_import


class SidekickWebImportTests(unittest.TestCase):
    def setUp(self):
        self.payload = {"skif": '{"version":5}', "default_io_level": 42}
        self.native = {"archetype": "Class_Blaster", "primary": "P", "secondary": "S",
                       "pools": [], "epic": None, "powers": [], "incarnates": {}}
        self.converter = Mock(return_value={"ok": True, "build": copy.deepcopy(self.native),
                                             "name": "Example", "issues": []})
        self.validator = Mock(return_value={"errors": [], "warnings": []})

    def invoke(self, payload=None, contract="/safe/external/contract"):
        with patch("sidekick_web_import.reconstruct_build", self.converter):
            return prepare_sidekick_import(self.payload if payload is None else payload,
                                           contract, {"Power": {}}, {"by_archetype": {}},
                                           {"UID": {}}, self.validator)

    def test_refuses_when_local_contract_is_not_configured(self):
        result = self.invoke(contract=None)
        self.assertFalse(result["ok"])
        self.assertNotIn("build", result)
        self.assertEqual(result["code"], "sidekick_contract_unavailable")
        self.converter.assert_not_called()

    def test_bad_payload_and_bad_io_default_are_rejected_before_conversion(self):
        for payload in ({}, {"skif": None}, {"skif": []},
                        {"skif": "x", "default_io_level": 0},
                        {"skif": "x", "default_io_level": True},
                        {"skif": "x", "default_io_level": 55},
                        {"skif": "x", "default_io_level": "50"}):
            self.converter.reset_mock()
            with self.subTest(payload=payload):
                result = self.invoke(payload)
                self.assertFalse(result["ok"])
                self.assertNotIn("build", result)
                self.converter.assert_not_called()

    def test_converter_refusal_surfaces_all_issues_without_partial_build(self):
        self.converter.return_value = {
            "ok": False, "issues": [
                {"reason": "state_not_mapped", "location": "build.attackChains", "detail": "chain"},
                {"reason": "unknown_enhancement_identity", "location": "build.primary.powers[0].slots[0]",
                 "detail": "not-in-catalog"}],
        }
        result = self.invoke()
        self.assertEqual(result["code"], "sidekick_unresolved")
        self.assertEqual(len(result["issues"]), 2)
        self.assertNotIn("build", result)
        self.validator.assert_not_called()

    def test_legality_errors_reject_an_otherwise_reconstructed_build(self):
        self.validator.return_value = {"errors": ["Too many slots", "Unpickable power"],
                                       "warnings": ["Check pool selections"]}
        result = self.invoke()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "sidekick_illegal_build")
        self.assertNotIn("build", result)
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(len(result["warnings"]), 1)

    def test_legal_build_returns_detached_copy_and_warnings(self):
        self.validator.return_value = {"errors": [], "warnings": ["Exemplar caution"]}
        payload = copy.deepcopy(self.payload)
        result = self.invoke(payload)
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "Example")
        self.assertEqual(result["build"], self.native)
        self.assertIsNot(result["build"], self.converter.return_value["build"])
        self.assertEqual(result["warnings"], ["Exemplar caution"])
        self.assertNotIn("source_skif", result)
        self.assertEqual(payload, self.payload)
        self.converter.assert_called_once()
        self.assertEqual(self.converter.call_args.kwargs["default_io_level"], 42)

    def test_no_client_control_of_server_contract_path(self):
        payload = {**self.payload, "contract_root": "/tmp/attacker"}
        self.invoke(payload)
        self.assertEqual(self.converter.call_args.args[3], "/safe/external/contract")

    def test_unexpected_converter_error_does_not_return_a_partial_build(self):
        self.converter.side_effect = ValueError("unsupported v4")
        result = self.invoke()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "sidekick_invalid_file")
        self.assertNotIn("build", result)


if __name__ == "__main__":
    unittest.main()
