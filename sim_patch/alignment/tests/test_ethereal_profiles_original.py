"""Independent original end-turn captures for the two pinned reference profiles."""
import copy
import os
from pathlib import Path
import sys
import unittest
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class EtherealProfilesRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_REPAIRED_ENGINE"]), REPO)
        cls.rows = read_json(REPO / "sim_patch/parity/tests/fixtures/ethereal-profiles-original.json.gz")

    def check_rows(self, rows, mode):
        self.assertEqual(len(rows), 4)
        for row in rows:
            with self.subTest(name=row["spec"]["name"]):
                views = [row["before"], *(step["after"] for step in row["trace"])]
                seeds = []
                for view in views:
                    value = view["game"]["combat_state"]["end_turn_shuffle"]
                    self.assertEqual(value["mode"], mode)
                    self.assertEqual(view["parity"]["runtime"]["ethereal_shuffle_mode"], mode)
                    raw = view["parity"]["raw_state"]["rng"]["java_util_Collections"]
                    self.assertEqual((value["shared_rng_initialized"], value["shared_seed48"]),
                                     (raw["initialized"], raw["seed48"]))
                    seeds.append(value["shared_seed48"])
                if mode == "basemod_seeded":
                    self.assertEqual(len(set(seeds)), 1)
                else:
                    self.assertNotEqual(seeds[0], seeds[-1])
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "coverage_gap", result.get("first_divergence", result.get("error")))
                self.assertTrue(result["observed_match"])
                self.assertFalse(result["resynchronized"])
                self.assertTrue(result["clone_checks"])
                self.assertEqual(result["checked_actions"], len(row["trace"]))
                for step, view in zip(result["steps"], views):
                    self.assertEqual(step["actual"]["end_turn_shuffle"], view["game"]["combat_state"]["end_turn_shuffle"])
                    self.assertNotIn("/game/combat_state/end_turn_shuffle/shared_seed48", step["field_audit"]["uncompared_fields"])

    def test_installed_profile_original(self):
        self.check_rows(self.rows[:4], "basemod_seeded")

    def test_shared_profile_original(self):
        self.check_rows(self.rows[4:], "java_shared")

    def test_same_visible_outcome_cannot_hide_rng_change(self):
        row = copy.deepcopy(self.rows[-1])
        row["trace"][0]["after"]["game"]["combat_state"]["end_turn_shuffle"]["shared_seed48"] ^= 1
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual([d["path"] for d in result["first_divergence"]["differences"]],
                         ["/end_turn_shuffle/shared_seed48"])
        self.assertEqual(result["first_divergence"]["index"], 0)
        self.assertFalse(result["resynchronized"])

    def test_profile_validation_and_legacy_gap(self):
        c = self.comparator
        game = copy.deepcopy(self.rows[4]["before"]["game"])
        good = game["combat_state"]["end_turn_shuffle"]
        for bad in ({**good, "mode": "guess"}, {**good, "shared_rng_initialized": 1},
                    *({**good, "shared_seed48": seed} for seed in (-1, 1 << 48, True, 1.5)),
                    {**good, "shared_rng_initialized": False}):
            game["combat_state"]["end_turn_shuffle"] = bad
            with self.subTest(bad=bad), self.assertRaises((ValueError, KeyError)):
                c.bridge.build_snapshot(game)
        view = copy.deepcopy(self.rows[0]["before"])
        del view["game"]["combat_state"]["end_turn_shuffle"]
        battle = c.import_battle(view)
        comparison = c.compare_battle(view, battle)
        self.assertEqual(battle.end_turn_shuffle["mode"], "basemod_seeded")
        self.assertTrue(any(g["kind"] == "missing_end_turn_shuffle_observation" for g in comparison["gaps"]))

    def test_game_context_setting_is_atomic_and_battle_owned(self):
        c = self.comparator; S = c.sts
        game = S.GameContext(S.CharacterClass.IRONCLAD, 123, 20)
        good = self.rows[4]["before"]["game"]["combat_state"]["end_turn_shuffle"]
        game.end_turn_shuffle = good
        for bad in ({**good, "mode": "guess"}, {**good, "shared_rng_initialized": 1},
                    *({**good, "shared_seed48": seed} for seed in (-1, 1 << 48, True, 1.5)),
                    {"mode": "java_shared", "shared_rng_initialized": True},
                    {**good, "shared_rng_initialized": False}):
            with self.subTest(bad=bad), self.assertRaises((ValueError, KeyError, RuntimeError, OverflowError)):
                game.end_turn_shuffle = bad
            self.assertEqual(game.end_turn_shuffle, good)
        for _ in range(10):
            if game.screen_state == S.ScreenState.BATTLE:
                break
            actions = [a for a in S.get_legal_game_actions(game) if not a.is_potion_action]
            self.assertTrue(actions)
            actions[0].execute(game)
        self.assertEqual(game.screen_state, S.ScreenState.BATTLE)
        battle = S.BattleContext(); battle.init(game)
        self.assertEqual(battle.end_turn_shuffle, good)
        S.SearchAction(S.SearchActionType.END_TURN).execute(battle)
        self.assertNotEqual(battle.end_turn_shuffle["shared_seed48"], good["shared_seed48"])
        self.assertEqual(game.end_turn_shuffle, good)
        for _ in range(200):
            if battle.outcome != S.Outcome.UNDECIDED:
                break
            S.mcts_recommend(battle, 64).execute(battle)
        self.assertNotEqual(battle.outcome, S.Outcome.UNDECIDED)
        battle.exit_battle(game)
        self.assertEqual(game.end_turn_shuffle, battle.end_turn_shuffle)


if __name__ == "__main__":
    unittest.main()
