"""Round 7 repair contracts use unchanged original captures, including private flags."""
import os
from pathlib import Path
import sys
import unittest
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import ActionMapper, Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class DrawSkullRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)

    def check_fixture(self, filename, energy, hp, strength):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures" / filename)
        self.assertEqual(len(rows), len(energy))
        for row, e, h, s in zip(rows, energy, hp, strength):
            with self.subTest(name=row["spec"]["name"]):
                p = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
                self.assertEqual((p["energy"], p["current_hp"]), (e, h))
                self.assertEqual(sum(x["amount"] for x in p["powers"] if x["id"] == "Strength"), s)
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "coverage_gap", result.get("first_divergence"))
                self.assertTrue(result["observed_match"])
                self.assertFalse(result["resynchronized"])
                self.assertTrue(result["clone_checks"])
                self.assertEqual(result["checked_actions"], len(row["trace"]))

    def test_draw_order(self):
        self.check_fixture("draw-power-order-original.json.gz", (0, 1, 1, 0), (50,) * 4, (0,) * 4)

    def test_max_hp_growth(self):
        self.check_fixture("red-skull-max-hp-original.json.gz", (2, 3, 2, 2), (44, 46, 45, 43), (0,) * 4)

    def test_extended_controls(self):
        self.check_fixture("draw-skull-repair-original.json.gz", (5, 5, 3, 1), (38, 43, 50, 50), (3, 0, 0, 0))

    def test_import_preserves_inactive_below_half_after_blocked_heal(self):
        row = read_json(REPO / "sim_patch/parity/tests/fixtures/draw-skull-repair-original.json.gz")[0]
        view = row["trace"][0]["after"]
        battle = self.comparator.import_battle(view)
        self.assertEqual((battle.player.cur_hp, battle.player.max_hp), (41, 85))
        self.assertFalse(battle.player.is_bloodied)
        self.assertFalse(battle.player.red_skull_active)
        snapshot = self.comparator.bridge.build_snapshot(view["game"])
        self.assertIs(snapshot["player"]["is_bloodied"], False)
        self.assertIs(snapshot["player"]["red_skull_active"], False)
        direct = self.comparator.sts.BattleContext.from_snapshot(snapshot, int(snapshot["seed"]))
        self.assertFalse(direct.player.is_bloodied)
        self.assertFalse(direct.player.red_skull_active)

    def test_void_energy_before_lethal_and_nonlethal_fire(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/void-terminal-original.json.gz")
        self.assertEqual(len(rows), 2)
        for i, row in enumerate(rows):
            with self.subTest(name=row["spec"]["name"]):
                final = row["trace"][-1]["after"]
                self.assertEqual(final["parity"]["raw_state"]["player_energy"], 3)
                battle = self.comparator.import_battle(row["before"])
                view = row["before"]
                mapper = ActionMapper(self.comparator, battle, view)
                for step in row["trace"]:
                    action = mapper.action(step["command"], view, battle)
                    self.assertTrue(action.is_valid(battle))
                    action.execute(battle)
                    view = step["after"]
                self.assertEqual((battle.player.energy, battle.player.cur_hp), (3, 47))
                expected = self.comparator.sts.Outcome.PLAYER_VICTORY if i == 0 else self.comparator.sts.Outcome.UNDECIDED
                self.assertEqual(battle.outcome, expected)


if __name__ == "__main__":
    unittest.main()
