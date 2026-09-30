"""Exhaust/Red Skull repair acceptance against unchanged original captures."""
import os
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"),
                     "set PARITY_REPAIRED_ENGINE for exhaust/Red Skull acceptance")
class ExhaustSkullRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)

    def check_rows(self, filename, hp, strength, enemies):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures" / filename)
        self.assertEqual(len(rows), len(hp))
        for i, row in enumerate(rows):
            with self.subTest(name=row["spec"]["name"]):
                c = row["trace"][-1]["after"]["game"]["combat_state"]
                self.assertEqual(c["player"]["current_hp"], hp[i])
                self.assertEqual(sum(p["amount"] for p in c["player"]["powers"]
                                     if p["id"] == "Strength"), strength[i])
                self.assertEqual([m["current_hp"] for m in c["monsters"]], enemies[i])
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "coverage_gap",
                                 (result.get("first_divergence") or {}).get("differences"))
                self.assertTrue(result["observed_match"])
                self.assertFalse(result["resynchronized"])
                self.assertTrue(result["clone_checks"])
                self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_exhaust_order_and_controls(self):
        self.check_rows("exhaust-power-order-original.json.gz", (50, 50, 50, 50),
                        (0, 0, 0, 0), [[20, 0], [20, 0], [15, 0], [26, 1]])

    def test_red_skull_revive_and_controls(self):
        self.check_rows("red-skull-revive-original.json.gz", (48, 48, 24, 48),
                        (999, 10, 999, 999), [[300]] * 4)

    def test_negative_cap_lizard_tail_and_healing_controls(self):
        self.check_rows("exhaust-skull-repair-original.json.gz", (48, 60, 43, 43),
                        (-996, 999, 3, 0), [[300]] * 4)


if __name__ == "__main__":
    unittest.main()
