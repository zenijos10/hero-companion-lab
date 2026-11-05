"""Hard slot legality shared by the editor, Mids and Sidekick imports."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import engine


def power(name, slot_count):
    return {"full_name": f"Test.Power.{name}", "display_name": name,
            "slots": [None] * slot_count, "slotCount": slot_count}


class SlotLegalityTests(unittest.TestCase):
    def reasons(self, powers):
        return engine.validate_build({"archetype": "Class_Blaster",
                                      "powers": powers})["errors"]

    def test_rejects_seventh_slot_on_a_power(self):
        errors = self.reasons([power("Health", 7)])
        self.assertTrue(any("6" in x and "Health" in x for x in errors), errors)

    def test_allows_exactly_67_additional_slots(self):
        powers = [power(str(i), 6) for i in range(13)]
        powers.append(power("last", 3))
        self.assertEqual(self.reasons(powers), [])

    def test_rejects_68_additional_slots(self):
        powers = [power(str(i), 6) for i in range(13)]
        powers.append(power("last", 4))
        errors = self.reasons(powers)
        self.assertTrue(any("67" in x for x in errors), errors)

    def test_zero_slot_unslottable_does_not_consume_budget(self):
        self.assertEqual(self.reasons([power("no slots", 0)]), [])


if __name__ == "__main__":
    unittest.main()
