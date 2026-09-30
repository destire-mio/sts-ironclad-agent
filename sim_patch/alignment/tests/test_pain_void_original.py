"""Repair acceptance uses the same original records as the frozen negative tests."""
import os
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE for repair acceptance")
class RepairedRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)

    def assert_sequence_matches(self, row):
        result = replay_sequence(self.comparator, row)
        first = result.get("first_divergence") or {}
        self.assertEqual(result["status"], "coverage_gap", first.get("differences"))
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])
        self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_pain_rupture_strength_damage_and_controls_match_original(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/pain-rupture-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, strength, hp, enemy_hp in zip(rows, (2, 4, 1, 0), (47, 47, 47, 48), (287, 286, 293, 288)):
            with self.subTest(name=row["spec"]["name"]):
                final = row["trace"][-1]["after"]["game"]["combat_state"]
                self.assertEqual(sum(p["amount"] for p in final["player"]["powers"] if p["id"] == "Strength"), strength)
                self.assertEqual(final["player"]["current_hp"], hp)
                self.assertEqual(final["monsters"][0]["current_hp"], enemy_hp)
                self.assert_sequence_matches(row)

    def test_void_energy_loss_and_controls_match_original(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/void-energy-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, energy, hp in zip(rows, (1, 1, 1, 2), (44, 47, 44, 44)):
            with self.subTest(name=row["spec"]["name"]):
                player = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
                self.assertEqual((player["energy"], player["current_hp"]), (energy, hp))
                self.assert_sequence_matches(row)


if __name__ == "__main__":
    unittest.main()
