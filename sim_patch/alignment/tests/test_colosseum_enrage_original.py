"""Original Colosseum second-monster Enrage and single-Nob cap controls."""
import os
from pathlib import Path
import sys
import unittest
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class ColosseumEnrageRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)

    def check_rows(self, filename, expected, index):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures" / filename)
        self.assertEqual(len(rows), 4)
        for row, strength in zip(rows, expected):
            with self.subTest(name=row["spec"]["name"]):
                monsters = row["trace"][-1]["after"]["game"]["combat_state"]["monsters"]
                self.assertEqual(monsters[index]["id"], "GremlinNob")
                self.assertEqual(sum(p["amount"] for p in monsters[index]["powers"] if p["id"] == "Strength"), strength)
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "coverage_gap", result.get("first_divergence"))
                self.assertTrue(result["observed_match"])
                self.assertFalse(result["resynchronized"])
                self.assertTrue(result["clone_checks"])
                self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_colosseum_second_monster(self):
        self.check_rows("colosseum-enrage-original.json.gz", (3, 1, 0, 0), 1)

    def test_single_nob_cap_controls(self):
        self.check_rows("enrage-disarm-control-original.json.gz", (997, 996, 4, 999), 0)


if __name__ == "__main__":
    unittest.main()
