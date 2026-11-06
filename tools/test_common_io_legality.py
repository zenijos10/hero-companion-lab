"""A common IO goes only where the power accepts it: solver, validator, real build.

Found by the Sidekick export round trip (2026-11-06): the solver put a Recharge
IO in Electric Armor's Lightning Reflexes, which accepts only Run Speed and Fly,
and /build/validate reported no error.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "ai")]
import engine
import server as app_server
import solver

LIGHTNING_REFLEXES = "Tanker_Defense.Electric_Armor.Lightning_Reflexes"


def slot(uid):
    return {"set_uid": None, "set_name": "Common IO", "piece_uid": uid, "piece_name": uid}


class CommonIoLegalityTests(unittest.TestCase):
    def test_admitting_word_comes_from_the_common_io_data(self):
        self.assertEqual(engine.COMMON_IO_ADMITTED_BY["Crafted_Recharge"], "recharge reduction")
        self.assertEqual(engine.COMMON_IO_ADMITTED_BY["Crafted_Run"], "run speed")
        # Named with a word no power uses ("Threat Duration"): never judged.
        self.assertNotIn("Crafted_Taunt", engine.COMMON_IO_ADMITTED_BY)

    def test_validate_refuses_an_io_the_power_does_not_take_on_the_apps_bare_payload(self):
        def errors(uid):
            build = {"archetype": "Class_Tanker", "powers": [
                {"full_name": LIGHTNING_REFLEXES, "pick_level": 1, "slots": [slot(uid)]}]}
            response = app_server.app.test_client().post("/build/validate", json=build)
            return [e for e in response.get_json()["errors"] if "Lightning Reflexes" in e]
        self.assertTrue(errors("Crafted_Recharge"))
        self.assertEqual(errors("Crafted_Run"), [])

    def test_solver_fills_only_what_the_power_accepts(self):
        rec = app_server.POWER_BY_FULL[LIGHTNING_REFLEXES]
        power = {"full_name": LIGHTNING_REFLEXES, "_slots": [], "base_recharge": 0,
                 "accepted_enhancement_types": rec["accepted_enhancement_types"]}
        solver._fill_generated_empties([power], 5)
        legal = {"Crafted_Run", "Crafted_Fly"}          # Run Speed / Flight Speed
        self.assertEqual(len(power["_slots"]), 1)
        self.assertIn(power["_slots"][0]["piece_uid"], legal)
        self.assertEqual({s["piece_uid"] for s in solver._fill_commons(power, 3)},
                         {"Crafted_Run", "Crafted_Fly"})
        nothing = {"full_name": "Test.Power.Nothing", "_slots": [], "base_recharge": 0,
                   "accepted_enhancement_types": ["Destiny Incarnate"]}
        solver._fill_generated_empties([nothing], 5)
        self.assertEqual(nothing["_slots"], [])
        self.assertEqual(solver._fill_commons(nothing, 2), [])

    def test_the_real_tanker_build_now_slots_lightning_reflexes_legally(self):
        client = app_server.app.test_client()
        kit = client.post("/build/autopick", json={
            "archetype": "Class_Tanker", "primary": "Tanker_Defense.Electric_Armor",
            "secondary": "Tanker_Melee.Brawling", "content": "itrial"}).get_json()
        solved = client.post("/build/solve", json={"archetype": "Class_Tanker",
                                                   "content": "itrial",
                                                   "powers": kit["powers"]}).get_json()
        build = {"archetype": "Class_Tanker", "powers": copy.deepcopy(solved["powers"])}
        errors = client.post("/build/validate", json=build).get_json()["errors"]
        self.assertEqual([e for e in errors if "can't take" in e], [])
        lightning = next(p for p in solved["powers"] if p["full_name"] == LIGHTNING_REFLEXES)
        self.assertNotIn("Crafted_Recharge", [(s or {}).get("piece_uid") for s in lightning["slots"]])


if __name__ == "__main__":
    unittest.main()
