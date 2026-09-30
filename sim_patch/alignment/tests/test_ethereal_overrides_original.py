"""Immutable original callbacks for Entrench, Ghostly Armor and generic controls."""
import os
from pathlib import Path
import sys
import unittest
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class EtherealOverridesRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)
        cls.rows = read_json(REPO / "sim_patch/parity/tests/fixtures/ethereal-overrides-original.json.gz")

    def check_row(self, index):
        row = self.rows[index]
        result = replay_sequence(self.c, row)
        self.assertEqual(result["status"], "coverage_gap", result.get("first_divergence", result.get("error")))
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])
        self.assertEqual(result["checked_actions"], len(row["trace"]))
        return row["trace"][-1]["after"]["game"]["combat_state"]

    def test_installed_callback_order(self):
        self.assertEqual(len(self.rows), 8)
        expected = (("Ghostly", "AscendersBane", "Dazed"), ("AscendersBane", "Ghostly", "Dazed"),
                    ("Dazed", "AscendersBane", "Ghostly Armor"))
        for index in range(5):
            with self.subTest(name=self.rows[index]["spec"]["name"]):
                combat = self.check_row(index)
                if index < len(expected):
                    self.assertEqual(tuple(c["id"] for c in combat["exhaust_pile"]), expected[index])

    def test_shared_callback_order(self):
        combat = self.check_row(6)
        self.assertEqual(combat["end_turn_shuffle"]["mode"], "java_shared")

    def test_no_ethereal_and_spoon_controls(self):
        combat = self.check_row(5)
        self.assertEqual(combat["exhaust_pile"], [])
        combat = self.check_row(7)
        self.assertEqual(len(combat["exhaust_pile"]), 3)

    def test_forethought_exhaust_and_discard(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/free-ethereal-original.json.gz")
        self.assertEqual(len(rows), 3)
        for index, row in enumerate(rows):
            with self.subTest(name=row["spec"]["name"]):
                result = replay_sequence(self.c, row)
                self.assertEqual(result["status"], "coverage_gap", result.get("first_divergence", result.get("error")))
                self.assertTrue(result["observed_match"])
                self.assertFalse(result["resynchronized"])
                self.assertTrue(result["clone_checks"])
                self.assertEqual(result["checked_actions"], 3)
                drawn = row["trace"][1]["after"]["game"]["combat_state"]["hand"]
                card_id = ("Ghostly Armor", "Carnage", "Strike_R")[index]
                self.assertTrue(next(c for c in drawn if c["id"] == card_id)["free_to_play_once"])
                final = row["trace"][2]["after"]["game"]["combat_state"]
                if index < 2:
                    self.assertFalse(final["exhaust_pile"][0]["free_to_play_once"])
                else:
                    self.assertFalse(final["exhaust_pile"])
                    self.assertTrue(next(c for c in final["hand"] if c["id"] == card_id)["free_to_play_once"])


if __name__ == "__main__":
    unittest.main()
