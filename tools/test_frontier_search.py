"""M6 battery: the frontier search (server/frontier_search.py) and /build/frontier.

Rule half (stubbed solver/validator/evaluator): illegal builds and broken
floors never enter, a budget still returns the discovered frontier, the
directions serving the chosen objectives run first, identical runs are
identical, a time budget is labeled non-deterministic, unmeasured candidates
are not admitted, and the claim never says "global".
Route half: a real build through /build/frontier gives legal members, keeps
picks locked, is repeatable, and an imported Sidekick build's alternatives
export back to Sidekick and re-import with the same picks (pinned checkout;
CI provides it).

Run: python tools/test_frontier_search.py
"""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-frontier-"))

import frontier_search as fs  # noqa: E402
import pareto  # noqa: E402

CONTRACT = ROOT / "_sidekick_contract_fixture"
OBJ = [pareto.Objective("single_target_damage"), pareto.Objective("defense")]
START = {"archetype": "Class_Test", "powers": [{"full_name": "A.B.C", "slots": [{"uid": "start"}]}]}

# what each direction's re-slot measures: damage vs defense tradeoffs
TABLE = {"start": (40, 30), "balanced": (45, 35), "damage": (80, 20),
         "hard_targets": (70, 15), "tank": (30, 40), "defense_softcap": (35, 45),
         "resistance_cap": (20, 20), "recharge_high": (50, 30), "endurance": (10, 10),
         "regeneration": (12, 12), "buffer": (44, 34), "healer": (41, 31),
         "controller": (45, 35), "debuffer": (60, 25)}
REVERSE = {(d["request"].get("role"), d["request"].get("content"),
            str(d["request"].get("custom_targets"))): d["id"] for d in fs.DIRECTIONS}


def stub_solve(build, request):
    key = REVERSE[(request.get("role"), request.get("content"), str(request.get("custom_targets")))]
    return [{"full_name": "A.B.C", "slots": [{"uid": key}]}]


def stub_eval(build):
    dmg, dfn = TABLE[build["powers"][0]["slots"][0]["uid"]]
    return {"values": {"single_target_damage": dmg, "defense": dfn}}, None


def run(**kw):
    args = dict(objectives=OBJ, floors={}, solve=stub_solve, validate=lambda b: [],
                evaluate=stub_eval, max_evaluations=40)
    args.update(kw)
    with patch.object(fs.build_ratings, "measure", side_effect=lambda ev: dict(ev["values"])):
        return fs.search(copy.deepcopy(START), **args)


def labels(result):
    return sorted(m["direction"] or "start" for m in result["members"])


class SearchRuleTests(unittest.TestCase):
    def test_full_run_keeps_every_tradeoff_and_drops_the_dominated(self):
        r = run()
        # balanced and controller measure the same: equal, so both stay (neither dominates)
        self.assertEqual(labels(r), ["balanced", "controller", "damage", "debuffer",
                                     "defense_softcap", "recharge_high"])
        self.assertEqual(r["search"]["stop_reason"], "exhausted")
        self.assertTrue(r["frontier"]["exact"])
        self.assertNotIn("global", r["claim"].replace("NOT proven to be the global", ""))
        outcomes = {e["direction"]: e["outcome"] for e in r["search"]["log"]}
        self.assertEqual(outcomes["endurance"], "dominated")
        self.assertEqual(outcomes[None], "admitted")      # the start competed, then lost

    def test_illegal_builds_never_enter(self):
        r = run(validate=lambda b: ["bad"] if b["powers"][0]["slots"][0]["uid"] == "damage" else [])
        self.assertNotIn("damage", labels(r))
        log = next(e for e in r["search"]["log"] if e["direction"] == "damage")
        self.assertEqual((log["outcome"], log["errors"]), ("illegal", ["bad"]))
        self.assertIn("hard_targets", labels(r))           # the next best offense steps up

    def test_floors_are_hard_constraints(self):
        r = run(floors={"defense": {"min": 30}})
        for m in r["members"]:
            self.assertGreaterEqual(m["objectives"]["defense"], 30)
        self.assertNotIn("damage", labels(r))
        self.assertEqual(next(e for e in r["search"]["log"] if e["direction"] == "damage")
                         ["outcome"], "below a floor")

    def test_budget_still_returns_the_frontier(self):
        r = run(max_evaluations=3)
        self.assertEqual(r["search"]["stop_reason"], "evaluation_budget")
        self.assertEqual(r["search"]["evaluations"], 3)
        self.assertTrue(r["members"])
        self.assertTrue(r["search"]["directions_not_tried"])

    def test_directions_serving_the_objectives_run_first(self):
        order = [d["id"] for d in fs.plan_directions(["healing"])]
        self.assertEqual(order[:2], ["balanced", "healer"])
        self.assertEqual(len(order), len(fs.DIRECTIONS))

    def test_identical_runs_are_identical(self):
        a, b = run(max_evaluations=6), run(max_evaluations=6)
        for r in (a, b):
            r["search"]["seconds"] = 0
        self.assertEqual(a, b)
        self.assertTrue(a["search"]["deterministic"])

    def test_time_budget_is_labeled(self):
        ticks = iter(range(0, 1000, 10))
        r = run(max_seconds=25, clock=lambda: next(ticks))
        self.assertEqual(r["search"]["stop_reason"], "time_budget")
        self.assertFalse(r["search"]["deterministic"])
        self.assertTrue(r["members"])

    def test_unmeasured_and_refused_candidates_never_enter(self):
        def evaluate(build):
            uid = build["powers"][0]["slots"][0]["uid"]
            if uid == "damage":
                return None, "PvP evaluation is not supported"
            if uid == "defense_softcap":
                return {"values": {"single_target_damage": 99, "defense": None}}, None
            return stub_eval(build)
        r = run(evaluate=evaluate)
        self.assertNotIn("damage", labels(r))
        self.assertNotIn("defense_softcap", labels(r))
        outcomes = {e["direction"]: e["outcome"] for e in r["search"]["log"]}
        self.assertEqual((outcomes["damage"], outcomes["defense_softcap"]),
                         ("not evaluated", "incomparable"))

    def test_same_slotting_is_evaluated_once(self):
        r = run(solve=lambda b, req: [{"full_name": "A.B.C", "slots": [{"uid": "balanced"}]}])
        self.assertEqual(r["search"]["evaluations"], 2)      # start + one re-slot
        self.assertTrue(any(e["outcome"].startswith("same slotting")
                            for e in r["search"]["log"]))

    def test_fingerprint_reads_the_piece(self):
        """Real slots name their piece as piece_uid: two slottings of the same sets
        with different pieces are different candidates."""
        a = [{"full_name": "A.B.C", "slots": [{"piece_uid": "Crafted_X_A", "set_uid": "X",
                                               "io_level": 50}]}]
        b = [{"full_name": "A.B.C", "slots": [{"piece_uid": "Crafted_X_F", "set_uid": "X",
                                               "io_level": 50}]}]
        self.assertNotEqual(fs.fingerprint(a), fs.fingerprint(b))
        self.assertEqual(fs.fingerprint(a), fs.fingerprint(copy.deepcopy(a)))
        img = copy.deepcopy(a)
        img[0]["slots"][0]["image"] = "x.png"                  # display fields do not count
        self.assertEqual(fs.fingerprint(a), fs.fingerprint(img))

    def test_request_parsing(self):
        objs, floors, budget, secs, size = fs.parse_request(
            {"objectives": ["defense", "recharge"], "directions": {"recharge": "min"},
             "floors": {"defense": {"min": 20}}, "max_evaluations": 999})
        self.assertEqual([(o.key, o.direction) for o in objs], [("defense", "max"), ("recharge", "min")])
        self.assertEqual((floors, budget, secs, size), ({"defense": {"min": 20}}, fs.MAX_EVALUATIONS,
                                                        None, None))
        for bad in ({"objectives": ["nope"]}, {"objectives": "defense"},
                    {"floors": {"defense": {"min": "x"}}}, {"floors": {"defense": {}}},
                    {"max_evaluations": 0}, {"directions": {"defense": "up"}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                fs.parse_request(bad)


class FrontierRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        cls.srv = srv
        cls.client = srv.app.test_client()
        at, pri, sec = "Class_Brute", "Brute_Melee.Super_Strength", "Brute_Defense.Invulnerability"
        ap = cls.client.post("/build/autopick", json={
            "archetype": at, "primary": pri, "secondary": sec, "content": "general"}).get_json()
        solved = cls.client.post("/build/solve", json={
            "archetype": at, "content": "general", "tier": "premium", "preserve": False,
            "powers": ap["powers"]}).get_json()
        cls.build = {"archetype": at, "primary": pri, "secondary": sec, "powers": solved["powers"]}

    def frontier(self, build, **kw):
        return self.client.post("/build/frontier", json=dict(build=build, **kw))

    def test_members_are_legal_locked_and_repeatable(self):
        body = {"objectives": ["single_target_damage", "defense", "resistance"],
                "max_evaluations": 4}
        first = self.frontier(self.build, **body).get_json()
        self.assertTrue(first["ok"])
        self.assertEqual(first["search"]["evaluations"], 4)
        self.assertEqual(first["scenario"], "rating_plus4")
        picks = sorted(p["full_name"] for p in self.build["powers"])
        for m in first["members"]:
            self.assertEqual(sorted(p["full_name"] for p in m["build"]["powers"]), picks)
            self.assertEqual(self.srv._complete_build_validation(m["build"]).get("errors") or [], [])
            self.assertEqual(set(m["objectives"]), set(body["objectives"]))
        second = self.frontier(self.build, **body).get_json()
        self.assertEqual([m["fingerprint"] for m in first["members"]],
                         [m["fingerprint"] for m in second["members"]])

    def test_refusals(self):
        self.assertEqual(self.frontier(dict(self.build, pvp=True)).status_code, 400)
        self.assertEqual(self.frontier(self.build, objectives=["bogus"]).status_code, 400)
        self.assertEqual(self.client.post("/build/frontier", json={}).status_code, 400)

    @unittest.skipUnless((CONTRACT / "fixtures/skif/v5/rb5d_browser_pass.skif").is_file(),
                         "pinned Sidekick contract checkout not present (CI provides it)")
    def test_sidekick_import_frontier_export_round_trip(self):
        source = (CONTRACT / "fixtures/skif/v5/rb5d_browser_pass.skif").read_text(encoding="utf-8")
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        env = {"HC_SIDEKICK_CONTRACT_DIR": str(CONTRACT / "contract/homecoming")}
        with patch.dict(os.environ, env), \
                patch.object(self.srv, "_sidekick_cache_dir", return_value=Path(cache.name)):
            imported = self.client.post("/build/import-sidekick", json={"skif": source}).get_json()
            self.assertTrue(imported.get("ok"), str(imported)[:300])
            result = self.frontier(imported["build"], max_evaluations=3).get_json()
            self.assertTrue(result["ok"], str(result)[:300])
            self.assertTrue(result["members"])
            for m in result["members"]:
                out = self.client.post("/build/export-sidekick",
                                       json={"build": m["build"], "allow_dropped_chains": True}
                                       ).get_json()
                self.assertTrue(out.get("ok"), str(out)[:400])
                back = self.client.post("/build/import-sidekick",
                                        json={"skif": out["skif"]}).get_json()
                self.assertTrue(back.get("ok"), str(back)[:300])
                self.assertEqual(sorted(p["full_name"] for p in back["build"]["powers"]),
                                 sorted(p["full_name"] for p in m["build"]["powers"]))


if __name__ == "__main__":
    unittest.main()
