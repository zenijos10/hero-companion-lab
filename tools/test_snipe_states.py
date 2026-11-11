"""Battery for v58: a sniper credits ONE damage state per shot
(tools/patch_snipe_states.py, owner's ruling 2026-11-11).

Pins: the rule's reach both ways (24 split + 4 folds, re-derived from the
shipped data with the tool's own rows put back); what moved and what stayed on
a representative record of each shape; and, through the REAL engine, that one
Ranged Shot is priced at the in-combat state only (a negative control: putting
the out-of-combat rows back restores the old double count).

Run: python tools/test_snipe_states.py
"""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "tools")]
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="hc-snipe-"))

import json  # noqa: E402

import patch_snipe_states as snipe  # noqa: E402

POWERS = json.loads((ROOT / "data" / "powers.json").read_text(encoding="utf-8"))
BY_FULL = {p["full_name"]: p for lst in POWERS.values() for p in lst}
HELP = json.loads((ROOT / "data" / "power_help.json").read_text(encoding="utf-8"))
DEF_RANGED_SHOT = "Defender_Ranged.Archery.Ranged_Shot"


def pve(rec, key="damage_effects"):
    return sorted((r["scale"], r.get("nmag", 1.0), r["damage_type"])
                  for r in rec.get(key) or [] if snipe._pve(r))


class SnipeRuleTests(unittest.TestCase):
    def test_rule_reaches_exactly_its_pinned_records(self):
        data = copy.deepcopy(POWERS)
        snipe.strip(data)
        rule = [p for lst in data.values() for p in lst
                if snipe.states_the_rule(HELP.get(p["full_name"])) and p.get("damage_effects")]
        scales = snipe.derive_scales(rule)
        self.assertEqual(scales, (4.5, 2.28))               # derived, never typed in
        split_records = []
        for p in rule:
            got = snipe.split(p, scales)
            if got:
                split_records.append((p["full_name"], *got))
        print(f"{len(split_records)} of {snipe.EXPECTED_COUNT} expected records split")
        self.assertEqual(len(split_records), snipe.EXPECTED_COUNT)
        folded, _refused = snipe.second_pass(data, HELP, split_records, True, scales)
        self.assertEqual(folded, snipe.EXPECTED_FOLDS)

    def test_scales_follow_the_data(self):
        """A patch that moves both snipe scales moves the rule with them."""
        def rec(out, inc, extra=()):
            rows = [{"scale": out, "nmag": 1.0, "damage_type": "Lethal", "probability": 1.0},
                    {"scale": inc, "nmag": 1.0, "damage_type": "Lethal", "probability": 1.0}]
            return {"damage_effects": rows + list(extra)}
        recs = [rec(4.0, 2.0) for _ in range(5)] + [rec(4.5, 3.56)]
        self.assertEqual(snipe.derive_scales(recs), (4.0, 2.0))
        out, kept = snipe.split(recs[0], (4.0, 2.0))
        self.assertEqual([r["scale"] for r in out], [4.0])
        self.assertIsNone(snipe.derive_scales([rec(4.0, 2.0), rec(5.0, 1.0), rec(6.0, 3.0)]))
        # the larger of the pair is the out-of-combat shot, whatever the row order
        self.assertEqual(snipe.derive_scales([rec(2.0, 4.0) for _ in range(3)]), (4.0, 2.0))

    def test_missing_probability_counts_like_the_engine(self):
        self.assertTrue(snipe._pve({"scale": 4.5}))               # engine reads 1.0
        self.assertFalse(snipe._pve({"scale": 4.5, "probability": 0.0}))
        self.assertFalse(snipe._pve({"scale": 4.5, "pv_mode": 2}))

    def test_form_detector_reproduces_the_file(self):
        raw = (ROOT / "data" / "powers.json").read_bytes()
        dumps = snipe.dumper(raw, POWERS)
        self.assertIsNotNone(dumps)
        self.assertEqual(dumps(POWERS), raw)
        compact = json.dumps({"a": [1, 2]}, separators=(",", ":")).encode()
        self.assertEqual(snipe.dumper(compact, {"a": [1, 2]})({"a": [1, 2]}), compact)
        self.assertIsNone(snipe.dumper(b'{"a":  [1, 2]}', {"a": [1, 2]}))

    def test_shipped_data_is_split(self):
        rec = BY_FULL[DEF_RANGED_SHOT]
        self.assertEqual(pve(rec, snipe.MOVED), [(4.5, 1.0, "Lethal")])
        self.assertIn((2.28, 1.0, "Lethal"), pve(rec))
        self.assertNotIn(4.5, [s for s, _n, _t in pve(rec)])
        # Sniper Blast's type split moved whole; its 2.28 nMag split stayed
        sb = BY_FULL["Defender_Ranged.Energy_Blast.Sniper_Blast"]
        self.assertEqual(pve(sb, snipe.MOVED), [(1.5, 1.0, "Smashing"), (3.0, 1.0, "Energy")])
        self.assertEqual(sum(n for s, n, _t in pve(sb) if s == 2.28), 1.0)

    def test_blaster_quick_twin_carries_the_in_combat_state(self):
        normal = BY_FULL["Redirects.Blaster_Archery.Ranged_Shot_Normal"]
        quick = BY_FULL["Redirects.Blaster_Archery.Ranged_Shot_Quick"]
        self.assertEqual(pve(normal), [])                      # out-of-combat moved aside
        self.assertEqual(pve(normal, snipe.MOVED), [(4.5, 1.0, "Lethal")])
        folded = [r for r in quick["damage_effects"] if r.get(snipe.FOLD)]
        # the same in-combat state the split siblings keep: the quick snipe plus
        # its expression row, so the shot is priced alike on every archetype
        shape = lambda rows: sorted((r["scale"], r["nmag"], r["damage_type"]) for r in rows)  # noqa: E731
        self.assertEqual(shape(folded),
                         shape(snipe.in_combat_rows(BY_FULL[DEF_RANGED_SHOT]["damage_effects"], 2.28)))
        self.assertEqual(len(folded), 2)
        self.assertEqual(sorted(folded[0][snipe.FOLD]),
                         ["Corruptor_Ranged.Archery.Ranged_Shot", DEF_RANGED_SHOT])

    def test_unrelated_records_are_untouched(self):
        for name in ("Dominator_Assault.Psionic_Assault.Psionic_Lance",   # stated exclusion
                     "Sentinel_Ranged.Archery.Ranged_Shot",               # one state already
                     "Blaster_Ranged.Fire_Blast.Blaze"):
            rec = BY_FULL[name]
            self.assertNotIn(snipe.MOVED, rec, name)
            self.assertFalse(any(r.get(snipe.FOLD) for r in rec.get("damage_effects") or []), name)


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server as srv
        import engine
        cls.srv, cls.engine = srv, engine

    def priced(self, power_by_full):
        ctx = self.srv._stat_ctx("Class_Defender")
        ctx["power_by_full"] = power_by_full
        build = {"archetype": "Class_Defender",
                 "powers": [{"full_name": DEF_RANGED_SHOT, "slots": [None]}]}
        attacks = self.engine._offense(build, {}, ctx).get("attacks") or []
        return next(a["damage"] for a in attacks if a["name"] == "Ranged Shot")

    def test_one_shot_is_one_state(self):
        now = self.priced(self.srv.POWER_BY_FULL)
        old = dict(self.srv.POWER_BY_FULL)
        rec = copy.deepcopy(old[DEF_RANGED_SHOT])
        data = {"x": [rec]}
        snipe.strip(data)                          # the pre-v58 record: both states
        old[DEF_RANGED_SHOT] = data["x"][0]
        before = self.priced(old)
        tiny = 2181.818115 * 1e-05
        print(f"Defender Ranged Shot per shot: {before} -> {now}")
        self.assertAlmostEqual(now / before, (2.28 + tiny) / (4.5 + 2.28 + tiny), places=2)


if __name__ == "__main__":
    unittest.main()
