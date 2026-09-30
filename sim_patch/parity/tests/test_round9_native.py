"""Round 9: detect Limit Break/Artifact mismatch and retain rejected Rampage hypothesis."""
import os
from pathlib import Path
import unittest
from sim_patch.parity.adapter import ActionMapper, Comparator, replay_sequence
from sim_patch.parity.core import read_json
REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "sim_patch/parity/tests/fixtures"


@unittest.skipUnless(os.environ.get("PARITY_ROUND9_ENGINE"), "set PARITY_ROUND9_ENGINE")
class Round9DetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_ROUND9_ENGINE"]), REPO)

    def matched(self, row):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "coverage_gap", result.get("first_divergence"))
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])
        self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_limit_break_artifact(self):
        rows = read_json(FIXTURES / "limit-break-artifact-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, strength, artifact in zip(rows, (-3, -3, -6, 6), (0, 0, 0, 1)):
            p = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
            powers = {x["id"]: x["amount"] for x in p["powers"]}
            self.assertEqual((powers["Strength"], powers.get("Artifact", 0)), (strength, artifact))
            self.assertEqual((p["current_hp"], p["energy"]), (50, 2))
        common = {"bombs": [0, 0, 0], "gold": 99, "energy_per_turn": 3, "card_draw_per_turn": 5}
        for row in rows[:2]:
            with self.subTest(name=row["spec"]["name"]):
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "mismatch")
                self.assertFalse(result["resynchronized"])
                self.assertEqual(result["first_divergence"]["index"], 1)
                self.assertEqual(result["first_divergence"]["differences"], [{
                    "path": "/legacy/player_powers", "kind": "value",
                    "original": {"STRENGTH": -3, **common},
                    "simulator": {"STRENGTH": -6, "ARTIFACT": 1, **common}}])
                self.assertTrue(all(not s["differences"] for s in result["steps"][:-1]))
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]): self.matched(row)

    def test_rampage_copy_matches_original(self):
        rows = read_json(FIXTURES / "rampage-copy-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, hp, base in zip(rows, (279, 276, 292, 288), (18, 24, 13, None)):
            with self.subTest(name=row["spec"]["name"]):
                final = row["trace"][-1]["after"]["game"]["combat_state"]
                self.assertEqual(final["monsters"][0]["current_hp"], hp)
                self.matched(row)
                # Generic pile comparison does not claim base-damage coverage.
                # Verify stored Rampage growth through an independent continuation.
                battle = self.comparator.import_battle(row["before"])
                view = row["before"]; mapper = ActionMapper(self.comparator, battle, view)
                for step in row["trace"]:
                    action = mapper.action(step["command"], view, battle)
                    self.assertTrue(action.is_valid(battle)); action.execute(battle)
                    view = step["after"]
                self.assertEqual(battle.monsters[0].cur_hp, hp)
                if base is not None:
                    original = [c for c in final["discard_pile"] if c["id"] == "Rampage"]
                    native = [c for c in battle.discard_pile if c.id == self.comparator.sts.CardId.RAMPAGE]
                    self.assertEqual(len(original), 1); self.assertEqual(len(native), 1)
                    self.assertEqual(original[0]["base_damage"], base)
                    self.assertEqual(native[0].special_data + 8, base)


if __name__ == "__main__":
    unittest.main()
