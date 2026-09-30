"""Repair contracts compare unchanged Round 8 original captures."""
import os
from pathlib import Path
import sys
import unittest
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class RuptureBrutalityRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)

    def replay(self, row):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "coverage_gap", result.get("first_divergence"))
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])
        self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_rupture_revive(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/rupture-revive-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, strength in zip(rows, (997, 998, 11, 999)):
            with self.subTest(name=row["spec"]["name"]):
                p = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
                self.assertEqual((p["current_hp"], p["energy"]), (48, 4))
                self.assertEqual(sum(x["amount"] for x in p["powers"] if x["id"] == "Strength"), strength)
                self.replay(row)

    def test_brutality_confusion(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/brutality-confusion-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, cost, hp, energy in zip(rows, (0, 0, 3, 1), (49, 49, 49, 50), (3, 3, 0, 2)):
            with self.subTest(name=row["spec"]["name"]):
                c = row["trace"][1]["after"]["game"]["combat_state"]
                self.assertEqual((c["hand"][5]["cost"], c["hand"][5]["base_cost"]), (cost, cost))
                self.assertEqual(c["player"]["current_hp"], hp)
                self.assertEqual(row["trace"][2]["after"]["game"]["combat_state"]["player"]["energy"], energy)
                self.replay(row)


if __name__ == "__main__":
    unittest.main()
