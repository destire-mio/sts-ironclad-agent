"""Round 6 detection contracts for the engine after the AoE/Urn repair.

Passing means the checker detects these recorded rule differences. Run in a
fresh process, separate from the older engine profiles in test_native.py and
test_repaired_native.py. Never edit original captures to accept a new engine.
"""
import os
from pathlib import Path
import unittest

from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "sim_patch/parity/tests/fixtures"


@unittest.skipUnless(os.environ.get("PARITY_ROUND6_ENGINE"),
                     "set PARITY_ROUND6_ENGINE for Round 6 detection")
class Round6DetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_ROUND6_ENGINE"]), REPO)

    def assert_difference(self, row, index, differences):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "mismatch")
        self.assertFalse(result["resynchronized"])
        self.assertEqual(result["first_divergence"]["index"], index)
        self.assertEqual(result["first_divergence"]["differences"], differences)
        self.assertEqual(len(result["steps"]), index + 2)
        for step in result["steps"][:-1]:
            self.assertEqual(step["differences"], [])

    def assert_control_matches(self, row):
        result = replay_sequence(self.comparator, row)
        first = result.get("first_divergence") or {}
        self.assertEqual(result["status"], "coverage_gap", first.get("differences"))
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])
        self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_red_skull_revive_strength_cap_and_three_controls(self):
        rows = read_json(FIXTURES / "red-skull-revive-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, hp, strength in zip(rows, (48, 48, 24, 48), (999, 10, 999, 999)):
            with self.subTest(name=row["spec"]["name"]):
                initial = row["before"]["game"]["combat_state"]["player"]
                final = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
                self.assertEqual((initial["current_hp"], initial["max_hp"]), (50, 80))
                self.assertEqual(final["current_hp"], hp)
                self.assertEqual(sum(p["amount"] for p in final["powers"]
                                     if p["id"] == "Strength"), strength)
        common = {"bombs": [0, 0, 0], "gold": 99,
                  "energy_per_turn": 3, "card_draw_per_turn": 5}
        self.assert_difference(rows[0], 1, [{
            "path": "/legacy/player_powers", "kind": "value",
            "original": {"STRENGTH": 999, **common},
            "simulator": {"STRENGTH": 996, **common}}])
        for row in rows[1:]:
            with self.subTest(name=row["spec"]["name"]):
                self.assert_control_matches(row)

    def test_exhaust_power_order_changes_damage_target_and_two_controls(self):
        rows = read_json(FIXTURES / "exhaust-power-order-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, enemy_hp, drawn in zip(rows, ((20, 0), (20, 0), (15, 0), (26, 1)),
                                        ("Burn", "Burn", "Burn", "Strike_R")):
            with self.subTest(name=row["spec"]["name"]):
                # The fire potion creates a 26/6 HP split without attack hooks.
                setup = row["trace"][0]["after"]["game"]["combat_state"]
                self.assertEqual([m["current_hp"] for m in setup["monsters"]], [26, 6])
                final = row["trace"][-1]["after"]["game"]["combat_state"]
                self.assertEqual(tuple(m["current_hp"] for m in final["monsters"]), enemy_hp)
                self.assertEqual(final["player"]["block"], 3)
                self.assertEqual([c["id"] for c in final["hand"]], [drawn])
        for row, simulator_hp in zip(rows[:2], (15, 13)):
            with self.subTest(name=row["spec"]["name"]):
                self.assert_difference(row, 5, [{"path": "/monsters/0/hp", "kind": "value",
                                                 "original": 20, "simulator": simulator_hp}])
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]):
                self.assert_control_matches(row)


if __name__ == "__main__":
    unittest.main()
