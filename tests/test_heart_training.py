"""Outcome, data-isolation and real simulator replay tests for the first run."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "agent"))
os.environ.setdefault("STS_LIGHTSPEED_BUILD", str(REPO.parent / "ironclad-alignment" / "build"))
import torch
torch.set_num_threads(1)
import armG_train as A
from heart_runtime import rollout, replay, fingerprint, branch_root, target, clock_input, training_samples
from heart_train import fit, signal_gate, split_seeds, usable_groups


class HeartTrainingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((REPO / "configs" / "heart_round1.json").read_text())
        cls.quick = {**cls.config, "simulations": 50, "root_min_floor": 1, "roots_per_seed": 3}
        cls.episode = rollout(9012345, cls.quick, record=True)

    def test_terminal_target_ignores_floors_and_faults(self):
        self.assertEqual(target("heart_win"), 1.0)
        for status in ("death", "act3_without_heart"):
            self.assertEqual(target(status), 0.0)
        for status in ("truncated", "timeout", "restore_error", "execution_error", "process_error"):
            self.assertIsNone(target(status))

    def test_seed_families_are_disjoint_and_reproducible(self):
        first, second = split_seeds(self.config), split_seeds(self.config)
        self.assertEqual(first, second)
        sets = [set(s) for s in first.values()]
        self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
        excluded = first["train"][0]
        self.assertNotIn(excluded, sum(split_seeds(self.config, [excluded]).values(), []))

    def test_actual_natural_prefix_replays_battle_and_rng(self):
        self.assertIn(self.episode["status"], ("death", "heart_win", "act3_without_heart"))
        self.assertTrue(any(r["kind"] == "battle" for r in self.episode["prefix"]))
        game = replay(self.episode["seed"], self.episode["prefix"], self.quick)
        self.assertEqual(game.floor_num, self.episode["floor"])
        self.assertEqual(game.cur_hp, self.episode["hp"])
        other = replay(self.episode["seed"], self.episode["prefix"], self.quick)
        self.assertEqual(fingerprint(game), fingerprint(other))

    def test_recorded_solver_matches_existing_agent(self):
        index = next(i for i, r in enumerate(self.episode["prefix"]) if r["kind"] == "battle")
        one = replay(self.episode["seed"], self.episode["prefix"][:index], self.quick)
        two = replay(self.episode["seed"], self.episode["prefix"][:index], self.quick)
        result = A.sts.resolve_battle_recorded(one, self.quick["simulations"], self.quick["boss_multiplier"])
        agent = A.sts.Agent()
        agent.simulation_count_base = self.quick["simulations"]
        agent.boss_simulation_multiplier = self.quick["boss_multiplier"]
        agent.pause_on_all_out_of_combat_decisions = True
        agent.playout(two)
        self.assertTrue(result["actions"])
        self.assertEqual(fingerprint(one), fingerprint(two))

    def test_replay_rejects_corrupt_prefix(self):
        bad = copy.deepcopy(self.episode["prefix"])
        bad[0]["before"] = "incorrect"
        with self.assertRaisesRegex(RuntimeError, "prefix pre-state"):
            replay(self.episode["seed"], bad, self.quick)

    def test_training_encoding_preserves_real_choices_and_rejects_false_outcomes(self):
        encoded=training_samples(self.episode,self.quick)
        fields=('seed','floor','screen','observation','descriptors','chosen')
        self.assertEqual([{k:g[k] for k in fields} for g in encoded],
                         [{k:g[k] for k in fields} for g in self.episode['samples']])
        bad=copy.deepcopy(self.episode);bad['prefix'][0]['before']='incorrect'
        with self.assertRaisesRegex(RuntimeError,'prefix pre-state'):
            training_samples(bad,self.quick)
        bad=copy.deepcopy(self.episode);bad['hp']+=1
        with self.assertRaisesRegex(ValueError,'terminal changed'):
            training_samples(bad,self.quick)

    def test_candidate_continuations_are_reproducible_and_isolated(self):
        self.assertTrue(self.episode["roots"])
        root = self.episode["roots"][0]
        original = replay(self.episode["seed"], self.episode["prefix"][:root["prefix_index"]], self.quick)
        initial = fingerprint(original)
        first = branch_root(self.episode, root, self.quick)
        second = branch_root(self.episode, root, self.quick)
        self.assertEqual(fingerprint(original), initial)
        self.assertTrue(first["complete"], first)
        self.assertEqual(len(first["outcomes"]), len(root["actions"]))
        compact = lambda r: [(o["target"], o["status"], o["floor"], o["hp"]) for o in r["outcomes"]]
        self.assertEqual(compact(first), compact(second))

    def test_faulty_or_constant_roots_do_not_pass_signal_gate(self):
        root = {"seed": 1, "chosen": 0, "targets": [0.0, 0.0]}
        self.assertFalse(signal_gate([root] * 20, [{**root, "seed": 2}], self.config)["passed"])
        mixed = {**root, "targets": [0.0, 1.0]}
        self.assertFalse(signal_gate([mixed] * 20, [{**mixed, "seed": 2}] * 4, self.config)["passed"])
        self.assertFalse(usable_groups([{"groups": [{"root": root, "complete": False}]}]))

    def test_optimizer_writes_changed_weights_and_rejects_seed_leakage(self):
        sample = {"seed": 1, "observation": [[0, 0.5]], "descriptors": [[[A.OFF_ACTION, 1.0]], [[A.OFF_ACTION + 1, 1.0]]], "chosen": 1}
        config = {**self.quick, "arch": [8], "bootstrap_epochs": 1, "batch_groups": 2}
        with tempfile.TemporaryDirectory() as path:
            result = fit(Path(path), [sample], [{**sample, "seed": 2}], config, "bootstrap")
            self.assertTrue(result["weights_changed"])
            self.assertTrue(Path(result["checkpoint"]).is_file())
            with self.assertRaisesRegex(ValueError, "seed family leakage"):
                fit(Path(path), [sample], [sample], config, "bootstrap")


if __name__ == "__main__":
    unittest.main()
