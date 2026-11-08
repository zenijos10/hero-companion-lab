"""Solve keeps a "count in totals" checkbox the player (or an import) set.

The owner's ruling (2026-11-07). Driven through the REAL /build/solve route with
the app's own payload shape (picks + the seven granted inherents, each power
carrying its include_in_totals as app.js sends it), per CLAUDE.md: a battery
that only feeds solver internals hand-built dicts can pass while the field fails.

Pins: an explicit choice comes back unchanged; unset still means the default;
a switched-off armor toggle earns no enhancement credit (the solver sizes
nothing for a power that is not running); engine/solver/routes share ONE rule.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
import engine
import server as srv

GRANTED = ["Inherent.Inherent.Brawl", "Inherent.Inherent.Sprint", "Inherent.Inherent.Rest",
           "Inherent.Fitness.Swift", "Inherent.Fitness.Hurdle", "Inherent.Fitness.Health",
           "Inherent.Fitness.Stamina"]
TOGGLE = "Scrapper_Defense.Invulnerability.Temp_Invulnerability"


class SolveKeepsCheckboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = srv.app.test_client()
        ap = cls.client.post("/build/autopick", json={
            "archetype": "Class_Scrapper", "primary": "Scrapper_Melee.Broad_Sword",
            "secondary": "Scrapper_Defense.Invulnerability", "content": "general"}).get_json()
        assert ap and ap["ok"], ap
        cls.picks = [p for p in ap["powers"] if not p["full_name"].startswith("Incarnate")]
        assert TOGGLE in [p["full_name"] for p in cls.picks]

    def solve(self, flags):
        """The app's main-Solve payload; `flags` overrides include_in_totals."""
        powers = []
        for p in self.picks + [{"full_name": fn, "slots": [None]} for fn in GRANTED]:
            rec = srv.POWER_BY_FULL[p["full_name"]]
            default = (rec["power_type"] == 1 if p["full_name"] in GRANTED
                       else rec["power_type"] in (1, 2))      # what app.js sets
            powers.append({"full_name": p["full_name"], "slots": p.get("slots") or [None],
                           "earned_slot_count": p.get("earned_slot_count"),
                           "pick_level": p.get("pick_level"),
                           "include_in_totals": flags.get(p["full_name"], default)})
        res = self.client.post("/build/solve", json={
            "archetype": "Class_Scrapper", "content": "general", "tier": "premium",
            "preserve": False, "powers": powers}).get_json()
        self.assertTrue(res and res["ok"], res)
        return {p["full_name"]: p for p in res["powers"]}

    def test_an_unticked_toggle_comes_back_unticked(self):
        out = self.solve({TOGGLE: False})
        self.assertIs(out[TOGGLE]["include_in_totals"], False)

    def test_the_app_granted_sprint_stays_unticked(self):
        out = self.solve({})
        self.assertIs(out["Inherent.Inherent.Sprint"]["include_in_totals"], False)
        self.assertIs(out["Inherent.Fitness.Health"]["include_in_totals"], True)

    def test_a_ticked_click_comes_back_ticked(self):
        click = next(fn for fn in (p["full_name"] for p in self.picks)
                     if srv.POWER_BY_FULL[fn]["power_type"] == 0)
        self.assertIs(self.solve({click: True})[click]["include_in_totals"], True)

    def test_a_switched_off_armor_toggle_earns_no_enhancement_credit(self):
        rec = srv.POWER_BY_FULL[TOGGLE]
        def resdef(include):
            p = dict(rec, include_in_totals=include)
            srv._attach_base_resdef([p], "Class_Scrapper", srv._stat_ctx("Class_Scrapper"), 75.0)
            return p.get("_base_rd")
        self.assertTrue(resdef(None))           # running by default: credited
        self.assertIsNone(resdef(False))        # switched off: nothing to size for

    def test_the_assessment_solve_keeps_the_checkbox_too(self):
        """_assess_solve (the import/improvement report's solve) carries the flag
        on its own copy of the power dict; pin it the way /build/solve is pinned."""
        powers = [{"full_name": p["full_name"], "slots": [None],
                   "include_in_totals": False if p["full_name"] == TOGGLE else None}
                  for p in self.picks]
        r = srv._assess_solve("Class_Scrapper", powers, {}, "premium", None, [], False,
                              False, False, with_powers=True, content="general")
        self.assertTrue(r and r[1], r)
        solved = {p["full_name"]: p for p in r[1]}
        self.assertIs(solved[TOGGLE]["include_in_totals"], False)

    def test_one_rule_for_engine_solver_and_routes(self):
        for include, kind, want in ((None, 2, True), (None, 1, True), (None, 0, False),
                                    (False, 2, False), (True, 0, True), (0, 1, False)):
            with self.subTest(include=include, kind=kind):
                self.assertIs(engine.counts_in_totals(
                    {"include_in_totals": include, "power_type": kind}), want)


if __name__ == "__main__":
    unittest.main()
