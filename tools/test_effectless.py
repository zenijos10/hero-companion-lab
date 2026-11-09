"""Battery for server/effectless.py and docs/EFFECTLESS-POWERS.md.

Pins the class counts both ways (a data change that moves one is a decision
to look at, not drift), checks the coverage denominator against an
independent count, and pins the cases each rule exists for.

A deliberate data change re-pins: update PINNED below and regenerate the doc.
Run: python tools/test_effectless.py
"""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]

import classify_effectless_powers as tool  # noqa: E402
import effectless  # noqa: E402

PINNED = {"effect_unread": 142, "mechanic": 100, "auto_granted": 49, "damaging_unread": 29,
          "modeled_elsewhere": 14, "unread_twins_damage": 2}


class EffectlessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.powers, cls.powersets, cls.help = tool.load()
        cls.rows = effectless.catalogue(cls.powers, cls.powersets, cls.help)
        cls.by_power = {r["power"]: r for r in cls.rows}

    def cls_of(self, name):
        return self.by_power[name]["class"]

    def test_every_effectless_pick_is_classified(self):
        """Denominator from an independent walk of the same sets."""
        records = effectless.pickable_records(self.powers, self.powersets)
        expected = sum(1 for r in records if not any(r.get(k) for k in effectless.EFFECT_KEYS))
        print(f"{len(self.rows)} of {expected} expected effect-less pickable records classified")
        self.assertEqual(len(self.rows), expected)
        self.assertGreater(expected, 300)

    def test_class_counts_are_pinned_both_ways(self):
        self.assertEqual(dict(Counter(r["class"] for r in self.rows)), PINNED)

    def test_redirect_with_twins_in_our_data(self):
        row = self.by_power["Blaster_Ranged.Archery.Ranged_Shot"]
        self.assertEqual(row["class"], "unread_twins_damage")
        self.assertEqual(sorted(row["twins"]), ["Redirects.Blaster_Archery.Ranged_Shot_Normal",
                                                "Redirects.Blaster_Archery.Ranged_Shot_Quick"])

    def test_a_storm_blast_attack_is_not_a_mastermind_upgrade(self):
        self.assertEqual(self.cls_of("Blaster_Ranged.Storm_Blast.Direct_Strike"), "damaging_unread")

    def test_mastermind_upgrades_are_modeled_elsewhere(self):
        for name in ("Mastermind_Summon.Mercenaries.Equip_Mercenary",
                     "Mastermind_Summon.Mercenaries.Tactical_Upgrade"):
            self.assertEqual(self.cls_of(name), "modeled_elsewhere")

    def test_a_damage_buff_is_not_damage(self):
        """'+DMG(All)' is a buff (Reach for the Limit), not damage dealt."""
        self.assertNotIn(self.cls_of("Blaster_Support.Martial_Manipulation.Reach_for_the_Limit"),
                         effectless.DAMAGING)

    def test_mode_switch_and_auto_granted(self):
        self.assertEqual(self.cls_of("Blaster_Ranged.Dual_Pistols.Swap_Ammo"), "mechanic")
        # the game issues the ammo types with Swap Ammo; they are never a pick
        self.assertEqual(self.cls_of("Blaster_Ranged.Dual_Pistols.Chemical_Ammunition"),
                         "auto_granted")

    def test_records_with_effects_are_never_classified(self):
        rec = self.powers["Blaster_Ranged.Fire_Blast"][0]
        self.assertTrue(effectless.has_effects(rec))
        self.assertIsNone(effectless.classify(rec, self.powers))

    def test_doc_is_current(self):
        self.assertEqual(tool.OUT.read_text(encoding="utf-8"), tool.render(self.rows),
                         "regenerate: python tools/classify_effectless_powers.py")


if __name__ == "__main__":
    unittest.main()
