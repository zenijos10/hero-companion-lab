"""M6 battery: Pareto dominance and the maintained frontier (server/pareto.py).

Pure rules, no game data. Covers the plan's 6.5 list for the comparator and
the frontier: rejection of a dominated candidate, removal of incumbents a
newcomer dominates, tradeoffs surviving together, max/min directions,
float near-ties, duplicates, order independence, the opt-in size cap being
labeled approximate, and missing measurements never entering.

Run: python tools/test_pareto.py
"""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import pareto  # noqa: E402

DMG, DEF, RECH = (pareto.Objective(k) for k in ("damage", "defense", "recharge"))
OBJ = [DMG, DEF, RECH]


def v(d, f, r):
    return {"damage": d, "defense": f, "recharge": r}


class DominanceTests(unittest.TestCase):
    def test_plan_example(self):
        a, b, c = v(90, 20, 60), v(75, 40, 75), v(60, 30, 50)    # S/D/B, A/B/A, B/C/C
        self.assertTrue(pareto.dominates(b, c, OBJ))
        self.assertFalse(pareto.dominates(a, b, OBJ))
        self.assertFalse(pareto.dominates(b, a, OBJ))

    def test_equal_is_not_dominance(self):
        self.assertFalse(pareto.dominates(v(1, 2, 3), v(1, 2, 3), OBJ))

    def test_float_noise_is_a_tie(self):
        noisy = v(0.1 + 0.2, 2, 3)
        self.assertFalse(pareto.dominates(noisy, v(0.3, 2, 3), OBJ))
        self.assertFalse(pareto.dominates(v(0.3, 2, 3), noisy, OBJ))
        self.assertFalse(pareto.dominates(v(1000.0004, 2, 3), v(1000.0, 2, 3), OBJ))
        self.assertTrue(pareto.dominates(v(1000.01, 2, 3), v(1000.0, 2, 3), OBJ))

    def test_minimize_direction(self):
        cost = [pareto.Objective("damage"), pareto.Objective("cost", pareto.MINIMIZE)]
        cheap, dear = {"damage": 50, "cost": 1}, {"damage": 50, "cost": 9}
        self.assertTrue(pareto.dominates(cheap, dear, cost))
        self.assertFalse(pareto.dominates(dear, cheap, cost))
        strong = {"damage": 60, "cost": 9}
        self.assertFalse(pareto.dominates(strong, cheap, cost))   # a real tradeoff

    def test_bad_direction_refused(self):
        with self.assertRaises(ValueError):
            pareto.Objective("x", "up")


class FrontierTests(unittest.TestCase):
    def fresh(self, **kw):
        return pareto.Frontier(OBJ, **kw)

    def test_dominated_candidate_is_rejected(self):
        f = self.fresh()
        f.insert("b", v(75, 40, 75))
        self.assertEqual(f.insert("c", v(60, 30, 50)), ("dominated", "b"))
        self.assertEqual([m[0] for m in f.members()], ["b"])

    def test_newcomer_removes_every_incumbent_it_dominates(self):
        f = self.fresh()
        f.insert("x", v(10, 10, 99))
        f.insert("y", v(50, 10, 10))
        f.insert("z", v(10, 50, 10))
        self.assertEqual(f.insert("w", v(60, 60, 20)), ("admitted", ["y", "z"]))
        self.assertEqual([m[0] for m in f.members()], ["w", "x"])

    def test_tradeoffs_survive_together(self):
        f = self.fresh()
        f.insert("offense", v(90, 10, 50))
        f.insert("defense", v(30, 45, 50))
        self.assertEqual(len(f.members()), 2)

    def test_weighted_average_never_decides(self):
        """A lower average with one unique strength stays."""
        f = self.fresh()
        f.insert("high_average", v(80, 40, 80))
        self.assertEqual(f.insert("one_trick", v(10, 41, 10))[0], "admitted")

    def test_duplicates_and_ties_are_deterministic(self):
        f = self.fresh()
        f.insert("a", v(1, 2, 3))
        self.assertEqual(f.insert("a", v(1, 2, 3)), ("duplicate", "a"))
        self.assertEqual(f.insert("b", v(1, 2, 3 + 1e-12))[0], "admitted")    # equal: both kept
        self.assertEqual([m[0] for m in f.members()], ["a", "b"])

    def test_arrival_order_does_not_matter(self):
        pts = {"a": v(90, 10, 50), "b": v(30, 45, 50), "c": v(20, 20, 20), "d": v(60, 30, 70),
               "e": v(60, 30, 70.0000000001), "f": v(10, 10, 99)}
        frontiers = set()
        for order in itertools.permutations(pts):
            f = self.fresh()
            for k in order:
                f.insert(k, pts[k])
            frontiers.add(tuple(m[0] for m in f.members()))
        self.assertEqual(frontiers, {("a", "b", "d", "e", "f")})

    def test_missing_measurement_never_enters(self):
        f = self.fresh()
        self.assertEqual(f.insert("x", {"damage": 1, "defense": None, "recharge": 3}),
                         ("incomparable", ["defense"]))
        self.assertEqual(f.insert("y", {"damage": float("nan"), "defense": 1, "recharge": 3}),
                         ("incomparable", ["damage"]))
        self.assertEqual(f.members(), [])

    def test_exact_unless_capped_and_cap_is_labeled(self):
        f = self.fresh()
        for i in range(8):
            f.insert(f"p{i}", v(i, 7 - i, 5))
        self.assertTrue(f.describe()["exact"])
        self.assertEqual(f.describe()["size"], 8)
        capped = self.fresh(max_size=4)
        for i in range(8):
            capped.insert(f"p{i}", v(i, 7 - i, 5))
        d = capped.describe()
        self.assertEqual((d["exact"], d["size"], d["dropped_by_cap"]), (False, 4, 4))
        self.assertIn("crowding", d["approximation"])
        kept = [m[0] for m in capped.members()]
        self.assertIn("p0", kept)              # the extremes of a tradeoff are never dropped
        self.assertIn("p7", kept)

    def test_strengths_name_why_each_member_survives(self):
        f = self.fresh()
        f.insert("offense", v(90, 10, 50))
        f.insert("defense", v(30, 45, 50))
        self.assertEqual(f.strengths("offense"), {"defense": ["damage"]})
        self.assertEqual(f.strengths("defense"), {"offense": ["defense"]})


if __name__ == "__main__":
    unittest.main()
