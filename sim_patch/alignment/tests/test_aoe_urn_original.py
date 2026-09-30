"""AoE/Urn repair acceptance against unchanged original-game captures."""
import os
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"),
                     "set PARITY_REPAIRED_ENGINE for AoE/Urn acceptance")
class AoeUrnRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)

    def check_rows(self, filename, player_hp, enemy_hp):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures" / filename)
        self.assertEqual(len(rows), len(player_hp))
        for row, hp, enemy in zip(rows, player_hp, enemy_hp):
            with self.subTest(name=row["spec"]["name"]):
                final = row["trace"][-1]["after"]["game"]["combat_state"]
                self.assertEqual(final["player"]["current_hp"], hp)
                self.assertEqual(final["monsters"][0]["current_hp"], enemy)
                result = replay_sequence(self.comparator, row)
                first = result.get("first_divergence") or {}
                self.assertEqual(result["status"], "coverage_gap", first.get("differences"))
                self.assertTrue(result["observed_match"])
                self.assertFalse(result["resynchronized"])
                self.assertTrue(result["clone_checks"])
                self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_cleave_reaper_and_controls_match_original(self):
        self.check_rows("pain-aoe-original.json.gz", (48, 52, 50, 48), (292, 296, 292, 294))

    def test_urn_pain_and_controls_match_original(self):
        self.check_rows("urn-pain-original.json.gz", (80, 80, 51, 80), (300, 300, 300, 300))

    def test_other_four_aoe_cards_match_original(self):
        self.check_rows("aoe-urn-repair-original.json.gz", (48, 48, 48, 48), (292, 279, 296, 290))


if __name__ == "__main__":
    unittest.main()
