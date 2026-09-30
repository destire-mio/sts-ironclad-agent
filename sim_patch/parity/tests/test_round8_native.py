"""Round 8 detection contracts: passing confirms known discrepancies remain."""
import os
from pathlib import Path
import unittest
from sim_patch.parity.adapter import ActionMapper, Comparator, replay_sequence
from sim_patch.parity.core import read_json
REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "sim_patch/parity/tests/fixtures"


@unittest.skipUnless(os.environ.get("PARITY_ROUND8_ENGINE"), "set PARITY_ROUND8_ENGINE")
class Round8DetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_ROUND8_ENGINE"]), REPO)

    def difference(self, row, expected):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "mismatch")
        self.assertFalse(result["resynchronized"])
        self.assertEqual(result["first_divergence"]["index"], 1)
        self.assertEqual(result["first_divergence"]["differences"], expected)
        self.assertEqual(len(result["steps"]), 3)
        self.assertTrue(all(not step["differences"] for step in result["steps"][:-1]))

    def control(self, row):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "coverage_gap", result.get("first_divergence"))
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])
        self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_rupture_revive_strength_caps(self):
        rows = read_json(FIXTURES / "rupture-revive-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, strength in zip(rows, (997, 998, 11, 999)):
            p = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
            self.assertEqual((p["current_hp"], p["energy"]), (48, 4))
            self.assertEqual(sum(x["amount"] for x in p["powers"] if x["id"] == "Strength"), strength)
        common = {"bombs": [0, 0, 0], "gold": 99, "energy_per_turn": 3, "card_draw_per_turn": 5}
        for row, rupture in zip(rows[:2], (1, 2)):
            with self.subTest(name=row["spec"]["name"]):
                self.difference(row, [{"path": "/legacy/player_powers", "kind": "value",
                    "original": {"STRENGTH": 996 + rupture, "RUPTURE": rupture, **common},
                    "simulator": {"RUPTURE": rupture, "STRENGTH": 996, **common}}])
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]): self.control(row)

    def test_brutality_confusion_blood_for_blood_cost(self):
        rows = read_json(FIXTURES / "brutality-confusion-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, cost, hp, energy in zip(rows, (0, 0, 3, 1), (49, 49, 49, 50), (3, 3, 0, 2)):
            c = row["trace"][1]["after"]["game"]["combat_state"]
            self.assertEqual(c["hand"][5]["id"], "Blood for Blood")
            self.assertEqual((c["hand"][5]["cost"], c["hand"][5]["base_cost"]), (cost, cost))
            self.assertEqual(c["player"]["current_hp"], hp)
            self.assertEqual(row["trace"][2]["after"]["game"]["combat_state"]["player"]["energy"], energy)
        for row in rows[:2]:
            with self.subTest(name=row["spec"]["name"]):
                self.difference(row, [{"path": f"/piles/hand/5/{field}", "kind": "value", "original": 0, "simulator": 1}
                                      for field in ("base_cost", "cost")])
                # Continue this independent simulator without importing the
                # original after-state: the cost error spends one extra energy.
                battle = self.comparator.import_battle(row["before"])
                view = row["before"]
                mapper = ActionMapper(self.comparator, battle, view)
                for step in row["trace"]:
                    action = mapper.action(step["command"], view, battle)
                    self.assertTrue(action.is_valid(battle)); action.execute(battle)
                    view = step["after"]
                self.assertEqual(battle.player.energy, 2)
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]): self.control(row)


if __name__ == "__main__":
    unittest.main()
