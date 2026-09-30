"""Repair contracts replay 16 unchanged original captures from Rounds 1/2/3/9."""
import os
from pathlib import Path
import sys
import unittest
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import ActionMapper, Comparator, replay_sequence
from sim_patch.parity.core import read_json
FIXTURES = REPO / "sim_patch/parity/tests/fixtures"


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class LimitBacklogRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)

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
            with self.subTest(name=row["spec"]["name"]):
                p = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
                powers = {x["id"]: x["amount"] for x in p["powers"]}
                self.assertEqual((powers["Strength"], powers.get("Artifact", 0)), (strength, artifact))
                self.assertEqual((p["current_hp"], p["energy"]), (50, 2))
                self.matched(row)

    def test_rampage_copies(self):
        rows = read_json(FIXTURES / "rampage-copies-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, hp, base in zip(rows, (261, 252, 279, 279), (23, 32, 18, 18)):
            with self.subTest(name=row["spec"]["name"]):
                self.matched(row)
                battle = self.comparator.import_battle(row["before"])
                view = row["before"]; mapper = ActionMapper(self.comparator, battle, view)
                for step in row["trace"]:
                    action = mapper.action(step["command"], view, battle)
                    self.assertTrue(action.is_valid(battle)); action.execute(battle)
                    view = step["after"]
                self.assertEqual(battle.monsters[0].cur_hp, hp)
                original = [c for c in view["game"]["combat_state"]["discard_pile"] if c["id"] == "Rampage"]
                native = [c for c in battle.discard_pile if c.id == self.comparator.sts.CardId.RAMPAGE]
                self.assertEqual(len(original), 1); self.assertEqual(len(native), 1)
                self.assertEqual(original[0]["base_damage"], base)
                self.assertEqual(native[0].special_data + 8, base)

    def test_parasite_overkill(self):
        rows = read_json(FIXTURES / "parasite-overkill-original.json.gz")
        self.assertEqual(len(rows), 3)
        for row, hp, enemy in zip(rows, (24, 38, 40), (25, 32, 25)):
            with self.subTest(name=row["spec"]["name"]):
                final = row["trace"][-1]["after"]["game"]["combat_state"]
                self.assertEqual((final["player"]["current_hp"], final["monsters"][0]["current_hp"]), (hp, enemy))
                self.matched(row)

    def test_whirlwind_fan(self):
        rows = read_json(FIXTURES / "whirlwind-fan-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row, hp, block in zip(rows, (33, 47, 43, 29), (0, 0, 4, 0)):
            with self.subTest(name=row["spec"]["name"]):
                p = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
                self.assertEqual((p["current_hp"], p["block"]), (hp, block))
                self.matched(row)

    def test_gamblers_brew_counter(self):
        rows = read_json(FIXTURES / "gamblers-brew-original.json.gz")
        self.assertEqual(len(rows), 1)
        # The observation build compares the discard counter at every checkpoint,
        # including four discards on confirm and its reset on the following turn.
        # Production lacks that exported field; native C++ tests cover its counter.
        self.matched(rows[0])


if __name__ == "__main__":
    unittest.main()
