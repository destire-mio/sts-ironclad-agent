"""Round 5 detection contracts for the engine containing the Pain/Void repair.

These tests require the recorded differences, not correct simulator behavior.
Run separately from test_native.py, which loads the older frozen engine.
"""
import os
from pathlib import Path
import unittest

from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json

REPO = Path(__file__).resolve().parents[3]


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"),
                     "set PARITY_REPAIRED_ENGINE for Round 5 detection")
class Round5DetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)

    def assert_difference(self, row, index, differences):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "mismatch")
        self.assertFalse(result["resynchronized"])
        self.assertEqual(result["first_divergence"]["index"], index)
        self.assertEqual(result["first_divergence"]["differences"], differences)
        # Reject an import or earlier-action difference as an explanation.
        self.assertEqual(len(result["steps"]), index + 2)
        for step in result["steps"][:-1]:
            self.assertEqual(step["differences"], [])

    def assert_control_matches(self, row):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "coverage_gap")
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])
        self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_pain_strength_changes_aoe_damage_but_anger_and_no_pain_match(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/pain-aoe-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, hp, enemy_hp, strength in zip(rows, (48, 52, 50, 48),
                                              (292, 296, 292, 294), (1, 1, 0, 1)):
            final = row["trace"][-1]["after"]["game"]["combat_state"]
            self.assertEqual(final["player"]["current_hp"], hp)
            self.assertEqual(final["monsters"][0]["current_hp"], enemy_hp)
            self.assertEqual(sum(p["amount"] for p in final["player"]["powers"]
                                 if p["id"] == "Strength"), strength)
        self.assert_difference(rows[0], 1, [
            {"path": "/monsters/0/hp", "kind": "value", "original": 292, "simulator": 291}])
        self.assert_difference(rows[1], 1, [
            {"path": "/monsters/0/hp", "kind": "value", "original": 296, "simulator": 295},
            {"path": "/player/hp", "kind": "value", "original": 52, "simulator": 53}])
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]):
                self.assert_control_matches(row)

    def test_urn_heals_before_pain_near_hp_cap_but_wounded_and_no_pain_match(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/urn-pain-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, before_hp, after_hp in zip(rows, (80, 79, 50, 80), (80, 80, 51, 80)):
            before = row["before"]["game"]["combat_state"]["player"]
            after = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
            self.assertEqual((before["current_hp"], before["max_hp"]), (before_hp, 80))
            self.assertEqual(after["current_hp"], after_hp)
        for row in rows[:2]:
            with self.subTest(name=row["spec"]["name"]):
                self.assert_difference(row, 0, [
                    {"path": "/player/hp", "kind": "value", "original": 80, "simulator": 79}])
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]):
                self.assert_control_matches(row)


if __name__ == "__main__":
    unittest.main()
