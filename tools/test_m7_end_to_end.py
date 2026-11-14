"""M7 battery: the whole rating workflow end to end, on real builds.

  A. A real Sidekick build: import -> validate -> evaluate -> rate -> compare ->
     Pareto alternatives -> export -> Sidekick re-import (pinned checkout; CI).
  B. Offline and LLM-free: the evaluate/compare/frontier routes run with every
     network door and the Claude CLI closed.
  C. Reproducible and versioned: identical inputs give identical outputs, and
     every artifact names its versions, scenario and request.
  D. Representative builds: all 15 playable archetypes rate; pets, support,
     healing, control, emergency protection and damage procs are each measured
     (procs with a negative control: stripping them lowers damage).
  E. Performance and memory budgets on a realistic build (printed, bounded).
  F. The four kinds of number never blur: no response carries a champion score,
     and each says what it is.

Run: python tools/test_m7_end_to_end.py
"""
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-m7-"))

import server as srv  # noqa: E402
import engine  # noqa: E402

CONTRACT = ROOT / "_sidekick_contract_fixture"
SKIF = CONTRACT / "fixtures/skif/v5/rb5d_browser_pass.skif"
C = srv.app.test_client()

# Generous ceilings (CI runners are slower than a desktop); the measured values print.
BUDGET = {"evaluate_s": 20.0, "compare_two_s": 40.0, "frontier_three_s": 150.0,
          "frontier_peak_mb": 512.0}
_BUILDS = {}


def generated(at, pri, sec, content="general"):
    key = (at, pri, sec, content)
    if key not in _BUILDS:
        ap = C.post("/build/autopick", json={"archetype": at, "primary": pri, "secondary": sec,
                                             "content": content}).get_json()
        solved = C.post("/build/solve", json={
            "archetype": at, "primary": pri, "secondary": sec, "content": content,
            "tier": "premium", "preserve": False, "powers": ap["powers"]}).get_json()
        _BUILDS[key] = {"archetype": at, "primary": pri, "secondary": sec,
                        "powers": solved["powers"]}
    return copy.deepcopy(_BUILDS[key])


def brute():
    return generated("Class_Brute", "Brute_Melee.Super_Strength", "Brute_Defense.Invulnerability")


def evaluate(build):
    res = C.post("/build/evaluate", json={"build": build})
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def walk_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_keys(v)


def llm_program(args):
    """The program a Popen call starts, if it is a model CLI (else None). Only the
    program decides: a checkout or temp path may well contain "claude", and the
    solver's CBC call passes such paths as arguments."""
    first = args[0] if isinstance(args, (list, tuple)) else str(args).split()[0]
    name = os.path.basename(str(first)).lower()
    return name if name.startswith(("claude", "anthropic")) else None


def without_timing(node):
    """Drop every measured wall-clock field (any key naming seconds), wherever it sits."""
    if isinstance(node, dict):
        return {k: without_timing(v) for k, v in node.items() if "seconds" not in k}
    if isinstance(node, list):
        return [without_timing(v) for v in node]
    return node


@unittest.skipUnless(SKIF.is_file(), "pinned Sidekick contract checkout not present (CI provides it)")
class A_SidekickEndToEnd(unittest.TestCase):
    def test_import_rate_compare_alternatives_export(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        env = {"HC_SIDEKICK_CONTRACT_DIR": str(CONTRACT / "contract/homecoming")}
        with patch.dict(os.environ, env), \
                patch.object(srv, "_sidekick_cache_dir", return_value=Path(cache.name)):
            imported = C.post("/build/import-sidekick",
                              json={"skif": SKIF.read_text(encoding="utf-8")}).get_json()
            self.assertTrue(imported.get("ok"), str(imported)[:300])
            build = imported["build"]
            # validate
            self.assertEqual(srv._complete_build_validation(copy.deepcopy(build)).get("errors") or [], [])
            # evaluate + rate, no optimization
            ev = evaluate(build)
            self.assertEqual(ev["ratings"]["status"], "rated")
            self.assertEqual(ev["unsupported"]["unknown_power_records"], [])
            # alternatives
            fr = C.post("/build/frontier", json={"build": build, "max_evaluations": 3}).get_json()
            self.assertTrue(fr["ok"] and fr["members"], str(fr)[:300])
            other = next((m for m in fr["members"] if not m["is_starting_build"]), None)
            # compare the imported build with an alternative
            if other is not None:
                cmp = C.post("/build/compare", json={"builds": [
                    {"label": "imported", "build": build},
                    {"label": other["label"], "build": other["build"]}]}).get_json()
                self.assertEqual((cmp["mode"], cmp["scope"]), ("comparison", "same_powersets"))
                self.assertTrue(all(c["rated"] for c in cmp["columns"]))
            # export every alternative and re-open it the way Sidekick's data reads it
            for m in fr["members"]:
                out = C.post("/build/export-sidekick", json={"build": m["build"],
                                                             "allow_dropped_chains": True}).get_json()
                self.assertTrue(out.get("ok"), str(out)[:300])
                # a passthrough field it could not keep is REPORTED, never silently lost
                if build.get("sidekick_slot_order") and not m["is_starting_build"]:
                    self.assertIn("dropped_slot_order", out)
                back = C.post("/build/import-sidekick", json={"skif": out["skif"]}).get_json()
                self.assertTrue(back.get("ok"), str(back)[:300])
                self.assertEqual(sorted(p["full_name"] for p in back["build"]["powers"]),
                                 sorted(p["full_name"] for p in m["build"]["powers"]))
            start = next(m for m in fr["members"] + [None] if m is None or m["is_starting_build"])
            if start is not None and build.get("sidekick_slot_order"):
                out = C.post("/build/export-sidekick", json={"build": start["build"],
                                                             "allow_dropped_chains": True}).get_json()
                self.assertFalse(out.get("dropped_slot_order"), "the untouched build keeps slotOrder")


class B_OfflineAndLlmFree(unittest.TestCase):
    def test_rating_routes_open_no_network_and_spawn_no_model(self):
        def no_network(*a, **k):
            raise AssertionError(f"network opened during a rating route: {a[:1]}")
        real_popen = subprocess.Popen

        def popen_guard(args, *a, **k):
            if llm_program(args):
                raise AssertionError(f"an LLM was invoked: {llm_program(args)}")
            return real_popen(args, *a, **k)

        build = brute()
        with patch.object(socket, "create_connection", no_network), \
                patch.object(socket.socket, "connect", no_network), \
                patch.object(subprocess, "Popen", popen_guard):
            self.assertTrue(evaluate(build)["ok"])
            cmp = C.post("/build/compare", json={"builds": [{"label": "a", "build": build}]})
            self.assertEqual(cmp.status_code, 200)
            fr = C.post("/build/frontier", json={"build": build, "max_evaluations": 2})
            self.assertEqual(fr.status_code, 200)
            self.assertTrue(fr.get_json()["members"])
        self.assertFalse(srv.AI_ENABLED, "the client ships AI-free")

    def test_guard_judges_the_program_not_its_paths(self):
        self.assertEqual(llm_program(["/opt/node22/bin/claude", "-p", "hi"]), "claude")
        self.assertEqual(llm_program("claude -p hi"), "claude")
        self.assertIsNone(llm_program(["/usr/bin/cbc", "/tmp/claude-0/x-pulp.mps"]))
        self.assertIsNone(llm_program(["/home/u/.claude/worktrees/x/cbc", "-solve"]))


class C_ReproducibleAndVersioned(unittest.TestCase):
    def test_identical_inputs_identical_outputs(self):
        build = brute()
        self.assertEqual(evaluate(build), evaluate(copy.deepcopy(build)))
        body = {"build": build, "objectives": ["defense", "recharge"], "max_evaluations": 3}
        a = C.post("/build/frontier", json=body).get_json()
        b = C.post("/build/frontier", json=copy.deepcopy(body)).get_json()
        self.assertEqual(without_timing(a), without_timing(b))
        # determinism is promised for budget-bounded runs; a time stop says otherwise
        self.assertTrue(a["search"]["deterministic"])
        self.assertEqual(a["search"]["stop_reason"], "evaluation_budget")

    def test_starting_build_is_evaluated_once(self):
        build = brute()
        real = srv._evaluate_build
        calls = []
        with patch.object(srv, "_evaluate_build",
                          lambda b, s, **kw: calls.append(kw) or real(b, s, **kw)):
            fr = C.post("/build/frontier", json={"build": build, "max_evaluations": 1}).get_json()
        self.assertEqual(fr["search"]["evaluations"], 1)      # only the start was offered
        self.assertEqual(len(calls), 1)                       # and it was evaluated once
        # a frontier reads measurements only: it never pays for the matchups
        self.assertEqual(calls[0].get("include_matchups"), False)

    def test_artifacts_carry_versions_scenario_and_request(self):
        build = brute()
        ev = evaluate(build)
        for k in ("app", "model", "database", "database_version", "scenario_fingerprint"):
            self.assertIn(k, ev["versions"])
        self.assertIn("thresholds_version", ev["ratings"])
        fr = C.post("/build/frontier", json={"build": build, "objectives": ["defense"],
                                             "floors": {"recharge": {"min": 1}},
                                             "max_evaluations": 2}).get_json()
        for k in ("app", "model", "database_version", "scenario_fingerprint", "rating_thresholds"):
            self.assertIn(k, fr["versions"])
        # one copy of each fact, from the evaluation that graded the builds
        self.assertEqual(fr["versions"]["rating_thresholds"], ev["ratings"]["thresholds_version"])
        self.assertFalse({"model_version", "database_version"} & set(fr))
        self.assertIn("picked_powersets", ev["build"])
        self.assertEqual(fr["versions"]["scenario_fingerprint"], ev["versions"]["scenario_fingerprint"])
        self.assertEqual(fr["request"]["objectives"], [{"key": "defense", "direction": "max"}])
        self.assertEqual(fr["request"]["floors"], {"recharge": {"min": 1}})
        self.assertEqual(fr["scenario"], ev["scenario"]["id"])
        json.dumps(fr, allow_nan=False)


class D_RepresentativeBuilds(unittest.TestCase):
    def test_every_playable_archetype_rates(self):
        ats = C.get("/archetypes").get_json()["archetypes"]
        rated = 0
        for a in ats:
            sets = C.get(f"/powersets/{a['name']}").get_json()
            name = lambda s: s.get("full_name") if isinstance(s, dict) else s  # noqa: E731
            build = generated(a["name"], name(sets["primary"][0]), name(sets["secondary"][0]))
            with self.subTest(archetype=a["name"]):
                ev = evaluate(build)
                json.dumps(ev, allow_nan=False)
                self.assertEqual(ev["ratings"]["status"], "rated")
                self.assertEqual(len(ev["ratings"]["categories"]), 36)
                rated += 1
        print(f"{rated} of {len(ats)} playable archetypes rated")
        self.assertEqual(rated, len(ats))

    def cats(self, at, pri, sec):
        return evaluate(generated(at, pri, sec))

    def test_pets_are_measured(self):
        ev = self.cats("Class_Mastermind", "Mastermind_Summon.Beast_Mastery",
                       "Mastermind_Buff.Cold_Domination")
        self.assertTrue(ev["build"]["summon_powers"])
        self.assertIn(ev["ratings"]["categories"]["pet_damage"]["grade"], tuple("SABCDF"))

    def test_support_healing_and_control_are_measured(self):
        cats = self.cats("Class_Defender", "Defender_Buff.Empathy",
                         "Defender_Ranged.Energy_Blast")["ratings"]["categories"]
        self.assertGreater(cats["healing"]["value"], 0)
        self.assertGreater(cats["buff_recharge"]["value"] or cats["buff_damage"]["value"], 0)
        ctl = self.cats("Class_Controller", "Controller_Control.Arsenal_Control",
                        "Controller_Buff.Cold_Domination")["ratings"]["categories"]
        self.assertGreater(ctl["control"]["value"], 0)
        self.assertGreater(ctl["buff_defense"]["value"], 0)

    def test_emergency_protection_is_kept_out_of_sustained(self):
        ev = self.cats("Class_Stalker", "Stalker_Melee.Broad_Sword", "Stalker_Defense.Bio_Organic_Armor")
        kinds = [e["kind"] for e in ev["measurements"]["survival"]["emergency_powers"]]
        self.assertIn("timed_click", kinds)

    def test_damage_procs_are_counted(self):
        build = brute()
        procs = set(engine._proc_table())
        placed = [(i, j) for i, p in enumerate(build["powers"])
                  for j, s in enumerate(p.get("slots") or [])
                  if isinstance(s, dict) and s.get("piece_uid") in procs]
        self.assertTrue(placed, "the generated Brute carries damage procs")
        stripped = copy.deepcopy(build)
        for i, j in placed:
            stripped["powers"][i]["slots"][j] = None
        # None is exactly what the app's clearSlot writes (app.js window.clearSlot)
        total = lambda b: (lambda o: o["scenario_single_target_dps"]["value"]  # noqa: E731
                           + o["scenario_aoe_dps_per_target"]["value"])(
            evaluate(b)["measurements"]["offense"])
        proc_drop = total(build) - total(stripped)
        self.assertGreater(proc_drop, 0)
        # control: emptying as many NON-proc pieces in non-attack powers costs less
        # damage, so the drop is the procs' and not the act of emptying slots
        others = [(i, j) for i, p in enumerate(build["powers"])
                  if not srv.POWER_BY_FULL.get(p["full_name"], {}).get("is_attack")
                  for j, s in enumerate(p.get("slots") or [])
                  if isinstance(s, dict) and s.get("piece_uid") not in procs][:len(placed)]
        self.assertEqual(len(others), len(placed))
        emptied = copy.deepcopy(build)
        for i, j in others:
            emptied["powers"][i]["slots"][j] = None
        self.assertLess(total(build) - total(emptied), proc_drop)


class E_PerformanceBudgets(unittest.TestCase):
    def test_realistic_build_stays_inside_budget(self):
        build = brute()
        evaluate(build)                                   # warm caches once
        t = time.perf_counter()
        evaluate(build)
        ev_s = time.perf_counter() - t
        other = generated("Class_Defender", "Defender_Buff.Force_Field", "Defender_Ranged.Energy_Blast")
        t = time.perf_counter()
        C.post("/build/compare", json={"builds": [{"label": "a", "build": build},
                                                  {"label": "b", "build": other}]})
        cmp_s = time.perf_counter() - t
        tracemalloc.start()
        t = time.perf_counter()
        fr = C.post("/build/frontier", json={"build": build, "max_evaluations": 3}).get_json()
        fr_s = time.perf_counter() - t
        peak_mb = tracemalloc.get_traced_memory()[1] / 2 ** 20
        tracemalloc.stop()
        print(f"evaluate {ev_s:.2f}s · compare(2) {cmp_s:.2f}s · frontier(3 evaluations) "
              f"{fr_s:.2f}s, peak traced memory {peak_mb:.0f} MB")
        self.assertEqual(fr["search"]["evaluations"], 3)
        self.assertLess(ev_s, BUDGET["evaluate_s"])
        self.assertLess(cmp_s, BUDGET["compare_two_s"])
        self.assertLess(fr_s, BUDGET["frontier_three_s"])
        self.assertLess(peak_mb, BUDGET["frontier_peak_mb"])


class F_NumberKinds(unittest.TestCase):
    def test_no_champion_score_and_each_response_names_its_kind(self):
        build = brute()
        ev = evaluate(build)
        cmp = C.post("/build/compare", json={"builds": [{"label": "a", "build": build}]}).get_json()
        fr = C.post("/build/frontier", json={"build": build, "max_evaluations": 2}).get_json()
        for name, body in (("evaluate", ev), ("compare", cmp), ("frontier", fr)):
            keys = set(walk_keys(body))
            with self.subTest(route=name):
                self.assertFalse({"score", "canonical_score", "champion_score"} & keys)
        self.assertEqual(ev["stage"], "measurements_and_ratings")      # raw + ratings
        self.assertIn(cmp["mode"], ("scorecard", "comparison"))
        self.assertEqual(fr["kind"], "discovered_frontier")
        m = fr["members"][0]
        # objectives (what was optimized), measurements (raw) and grades (ratings) are separate
        self.assertTrue(set(m["objectives"]) <= set(m["measurements"]))
        self.assertEqual(set(m["grades"]), set(m["measurements"]))


if __name__ == "__main__":
    unittest.main()
