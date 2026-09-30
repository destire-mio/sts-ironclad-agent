"""Round 7 detection contracts after the exhaust/Red Skull queue repair.

These require the recorded differences. Passing is detection, not repair.
"""
import os
from pathlib import Path
import unittest
from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "sim_patch/parity/tests/fixtures"


@unittest.skipUnless(os.environ.get("PARITY_ROUND7_ENGINE"), "set PARITY_ROUND7_ENGINE")
class Round7DetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_ROUND7_ENGINE"]), REPO)

    def assert_difference(self, row, index, expected):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "mismatch")
        self.assertFalse(result["resynchronized"])
        self.assertEqual(result["first_divergence"]["index"], index)
        self.assertEqual(result["first_divergence"]["differences"], expected)
        self.assertEqual(len(result["steps"]), index + 2)
        for step in result["steps"][:-1]:
            self.assertEqual(step["differences"], [])

    def assert_control(self, row):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "coverage_gap",
                         (result.get("first_divergence") or {}).get("differences"))
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])
        self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_draw_power_order_changes_energy_and_legal_actions(self):
        rows = read_json(FIXTURES / "draw-power-order-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, energy in zip(rows, (0, 1, 1, 0)):
            with self.subTest(name=row["spec"]["name"]):
                c = row["trace"][-1]["after"]["game"]["combat_state"]
                self.assertEqual(c["player"]["energy"], energy)
                self.assertEqual([m["current_hp"] for m in c["monsters"]], [14, 0])
                self.assertEqual(c["player"]["block"], 2)
        self.assert_difference(rows[0], 3, [
            {"path": "/player/energy", "kind": "value", "original": 0, "simulator": 1},
            {"path": "/legal_actions", "kind": "length", "original": 1, "simulator": 2}])
        for row in rows[1:]:
            with self.subTest(name=row["spec"]["name"]):
                self.assert_control(row)

    def test_max_hp_growth_removes_strength_without_active_red_skull(self):
        rows = read_json(FIXTURES / "red-skull-max-hp-original.json.gz")
        self.assertEqual(len(rows), 4)
        for i, (row, hp, maximum) in enumerate(zip(rows, (44, 46, 45, 43), (83, 85, 83, 83))):
            with self.subTest(name=row["spec"]["name"]):
                before = row["before"]["parity"]["raw_state"]
                skull = next(r for r in before["relics"] if r["class"].endswith(".RedSkull"))
                self.assertEqual(skull["fields"]["RedSkull.isActive"], i == 3)
                self.assertEqual(before["player"]["AbstractCreature.isBloodied"], i == 3)
                p = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
                self.assertEqual((p["current_hp"], p["max_hp"]), (hp, maximum))
                self.assertEqual(sum(v["amount"] for v in p["powers"] if v["id"] == "Strength"), 0)
        common = {"bombs": [0, 0, 0], "gold": 99, "energy_per_turn": 3, "card_draw_per_turn": 5}
        for row in rows[:2]:
            with self.subTest(name=row["spec"]["name"]):
                self.assert_difference(row, 0, [{"path": "/legacy/player_powers", "kind": "value",
                                                "original": common, "simulator": {"STRENGTH": -3, **common}}])
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]):
                self.assert_control(row)


if __name__ == "__main__":
    unittest.main()
