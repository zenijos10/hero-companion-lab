"""Pinned optimizer-score parity for first_principles.encounter_value.

The evaluation contract reads display-only keys out of encounter_value; this
battery guarantees those additions never move the SCORE. Frozen builds (picks
and slotting stored in the fixture, so no solve runs) are scored in every
scenario and must reproduce the pinned contribution/my_dps/amplified/prevented
exactly at the pinned MODEL_VERSION.

A model bump is a deliberate score change: re-pin with
    python tools/test_encounter_parity.py --write
and say so in the commit. A mismatch WITHOUT a model bump is a regression.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-encounter-parity-"))

import server as srv  # noqa: E402
import engine  # noqa: E402
import first_principles as fp  # noqa: E402
import role_output  # noqa: E402

FIXTURE = ROOT / "tools" / "fixtures" / "encounter_parity.json"
PINNED_KEYS = ("contribution", "my_dps", "amplified", "prevented", "availability", "ttl")
CASES = (
    ("Class_Mastermind", "Mastermind_Summon.Mercenaries", "Mastermind_Buff.Force_Field"),
    ("Class_Controller", "Controller_Control.Mind_Control", "Controller_Buff.Kinetics"),
    ("Class_Brute", "Brute_Melee.Super_Strength", "Brute_Defense.Invulnerability"),
    ("Class_Dominator", "Dominator_Control.Plant_Control", "Dominator_Assault.Fiery_Assault"),
)

UPGRADES = {"Mastermind_Summon.Mercenaries": ("Mastermind_Summon.Mercenaries.Equip_Mercenary",
                                              "Mastermind_Summon.Mercenaries.Tactical_Upgrade")}


def _score(archetype, powers, scenario):
    ctx = srv._stat_ctx(archetype)
    ctx["power_by_full"] = srv.POWER_BY_FULL
    arow = srv.ARCH_BY_NAME[archetype]
    totals = engine.calculate_build({"archetype": archetype, "powers": powers}, srv.SET_BONUSES,
                                    res_cap=round(arow["res_cap"] * 100, 1), ctx=dict(ctx))
    ev = fp.encounter_value(archetype, powers, ctx, totals, scenario=scenario,
                            arch_row=arow, role_output_mod=role_output)
    return {k: ev[k] for k in PINNED_KEYS}


def write_fixture():
    client = srv.app.test_client()
    builds = []
    for archetype, primary, secondary in CASES:
        ap = client.post("/build/autopick", json={
            "archetype": archetype, "primary": primary, "secondary": secondary,
            "content": "general"}).get_json()
        solved = client.post("/build/solve", json={
            "archetype": archetype, "content": "general", "tier": "premium",
            "preserve": False, "powers": ap["powers"]}).get_json()
        powers = [{"full_name": p["full_name"], "slots": p.get("slots") or [],
                   "include_in_totals": p.get("include_in_totals")}
                  for p in solved["powers"]]
        # autopick leaves MM upgrades out; they drive the re-upgrade overhead term
        powers += [{"full_name": fn, "slots": [], "include_in_totals": None}
                   for fn in UPGRADES.get(primary, ())]
        builds.append({"archetype": archetype, "powers": powers,
                       "expected": {s: _score(archetype, powers, s) for s in fp.SCENARIOS}})
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps({"model_version": fp.MODEL_VERSION, "builds": builds},
                                  indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"pinned {len(builds)} builds x {len(fp.SCENARIOS)} scenarios at model v{fp.MODEL_VERSION}")


class EncounterParityTests(unittest.TestCase):
    def test_scores_match_the_pinned_fixture(self):
        pinned = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(pinned["model_version"], fp.MODEL_VERSION,
                         "MODEL_VERSION moved: re-pin deliberately with --write")
        checked = 0
        for build in pinned["builds"]:
            for scenario, want in build["expected"].items():
                with self.subTest(archetype=build["archetype"], scenario=scenario):
                    self.assertEqual(_score(build["archetype"], build["powers"], scenario), want)
                    checked += 1
        expected = len(pinned["builds"]) * len(fp.SCENARIOS)
        print(f"{checked} of {expected} expected build x scenario scores checked")
        self.assertEqual(checked, expected)


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_fixture()
    else:
        unittest.main()
