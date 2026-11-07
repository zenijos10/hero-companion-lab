"""Solve keeps a "count in totals" checkbox the player (or an import) set.

The owner's ruling (2026-11-07): before it, solver._finalize_powers rebuilt
include_in_totals from power_type on every Solve, so an unticked toggle came
back ticked and a Sidekick switch imported as off was undone by the first
Solve. Unset still means the default (toggles and Autos on, clicks off).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server")]
import solver


def power(full, power_type, include=None):
    p = {"full_name": full, "power_type": power_type, "_slots": [],
         "accepted_set_category_ids": [], "accepted_set_categories": []}
    if include is not None:
        p["include_in_totals"] = include
    return p


class SolveKeepsCheckboxTests(unittest.TestCase):
    def finalize(self, *powers):
        return {p["full_name"]: p["include_in_totals"]
                for p in solver._finalize_powers(list(powers))}

    def test_an_explicit_choice_survives_the_solve(self):
        out = self.finalize(power("Toggle_Off", 2, False), power("Click_On", 0, True),
                            power("Auto_Off", 1, False))
        self.assertEqual(out, {"Toggle_Off": False, "Click_On": True, "Auto_Off": False})

    def test_unset_follows_the_power_type_default(self):
        out = self.finalize(power("Toggle", 2), power("Click", 0), power("Auto", 1))
        self.assertEqual(out, {"Toggle": True, "Click": False, "Auto": True})

    def test_a_locked_power_keeps_it_too(self):
        locked = dict(power("Locked_Toggle", 2, False), _lock_all=True)
        self.assertEqual(self.finalize(locked), {"Locked_Toggle": False})


if __name__ == "__main__":
    unittest.main()
