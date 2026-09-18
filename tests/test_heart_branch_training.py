"""Family isolation, cached-score fidelity, and full-run evaluation accounting."""
from collections import Counter
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
import heart_branch_training as T


class BranchTrainingTest(unittest.TestCase):
    def test_two_states_can_share_a_family_but_cannot_cross_splits(self):
        roles = {'train': [10, 20], 'validation': [30], 'selected_development': [30]}
        roots = [{'id': 'a', 'seed': 10, 'prefix_index': 1, 'split': 'fit'},
                 {'id': 'b', 'seed': 10, 'prefix_index': 2, 'split': 'fit'},
                 {'id': 'c', 'seed': 20, 'prefix_index': 1, 'split': 'label_holdout'}]
        self.assertEqual(T.validate_families(roots, roles), {'fit': 1, 'label_holdout': 1})
        with self.assertRaisesRegex(ValueError, 'crosses'):
            T.validate_families([roots[0], {**roots[1], 'split': 'label_holdout'}], roles)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            T.validate_families(roots + [roots[0]], roles)

    def test_previous_pilot_and_validation_families_are_excluded(self):
        roles = {'train': [10, 20], 'validation': [30], 'selected_development': [30]}
        state = {'id': 'a', 'seed': 10, 'prefix_index': 1, 'split': 'fit'}
        with self.assertRaisesRegex(ValueError, 'excluded'):
            T.validate_families([state], roles, excluded=[10])
        with self.assertRaisesRegex(ValueError, 'excluded'):
            T.validate_families([{**state, 'seed': 30}], roles)

    def test_nested_seed_inventory_covers_reservations_without_treating_counts_as_seeds(self):
        value = {'train': [101], 'final_test': [102], 'nested': [{'reservation': [103, 104]}],
                 'seed_rng': 1401, 'count': 512, 'provenance': [{'seed': 105, 'path': 'file'}]}
        self.assertEqual(T.seed_values(value), {101, 102, 103, 104, 105})
        self.assertEqual(T.seed_values({}), set())
        with self.assertRaisesRegex(ValueError, 'overlap'):
            T.assert_fresh([106, 104], T.seed_values(value))

    def test_random_draw_rejects_history_and_duplicate_seeds(self):
        with patch.object(T.secrets, 'randbelow', side_effect=[1, 2, 2, 3]):
            seeds = T.fresh_seeds(2, {10000001})
        self.assertEqual(seeds, [10000002, 10000003])
        T.assert_fresh(seeds, {10000001})

    def test_inventory_uses_repository_legacy_file_not_frozen_runtime_path(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'eval').mkdir()
            (base / 'eval/eval_seeds_50.txt').write_text('105\n106\n')
            T.H.write_json(base / 'runs/collection/seeds.json', {'train': [101], 'final_test': [102]})
            T.H.write_json(base / 'runs/collection/batches/01/seeds.json', {'train': [103, 104]})
            used, sources = T.historical_seeds(base / 'runs')
            self.assertEqual(used, {101, 102, 103, 104, 105, 106})
            self.assertEqual(len(sources), 3)

    def test_family_sampling_does_not_double_weight_a_two_state_seed(self):
        roots = [{'id': 'a', 'seed': 10}, {'id': 'b', 'seed': 10}, {'id': 'c', 'seed': 20}]
        samples = T.family_sample(roots, random.Random(7), 6000)
        counts = Counter(r['seed'] for r in samples)
        self.assertTrue(2700 < counts[10] < 3300, counts)
        self.assertEqual({r['id'] for r in samples}, {'a', 'b', 'c'})

    def test_cached_features_preserve_scores_and_preference_gradients(self):
        T.H.torch.set_num_threads(1)
        root = REPO / 'runs/heart-branch-pilot-20260916-01'
        state = next(r for r in T.H.read_json(root / 'roots.json.gz') if r['seed'] == 974606833)
        checkpoint = T.H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True)
        net = T.H.load_scorer(checkpoint)
        values, _ = T.H.matrix([state])
        features = {state['id']: net.features(values).detach()}
        direct = T.G.losses(net, [state])[1][0]
        cached = T.cached_scores(net, [state], features)[0]
        self.assertTrue(T.H.torch.allclose(direct, cached, atol=1e-5, rtol=1e-5))
        for score in (direct, cached):
            net.zero_grad()
            T.P.preference_loss(score, [0, 1, 0], state['candidates']).backward()
            grad = T.H.torch.cat([p.grad.flatten() for p in net.parameters()]).clone()
            if score is direct:
                expected = grad
            else:
                self.assertTrue(T.H.torch.allclose(expected, grad, atol=2e-6, rtol=2e-6))

    def test_paired_outcomes_require_both_valid_arms_and_fixed_model_hashes(self):
        def row(seed, win, sha):
            return {'seed': seed, 'status': 'heart_win' if win else 'death', 'target': float(win),
                'checkpoint_sha256': sha, 'replay_verified': True, 'terminal_state_verified': True,
                'terminal_fingerprint': 'fp', 'prefix': [1], 'policy_start_floor': 0,
                'act': 4, 'keys': [True] * 3}
        shas = {'baseline': 'old', 'candidate': 'new'}
        results = {('baseline', 1): row(1, False, 'old'), ('candidate', 1): row(1, True, 'new'),
                   ('baseline', 2): row(2, True, 'old'), ('candidate', 2): row(2, False, 'new')}
        summary = T.paired_counts([1, 2], results, shas)
        self.assertEqual(summary['paired_outcomes'], {'candidate_only': 1, 'baseline_only': 1})
        self.assertEqual(summary['net_candidate_wins'], 0)
        results['candidate', 2]['status'] = 'timeout'
        summary = T.paired_counts([1, 2], results, shas)
        self.assertFalse(summary['complete'])
        self.assertIsNone(summary['heart_win_rates']['candidate'])
        self.assertEqual(summary['execution_failure_seeds'], [2])

    def test_natural_evaluation_replans_the_recorded_full_game(self):
        T.H.torch.set_num_threads(1)
        source = REPO / 'runs/heart-training-set-evaluation-20260915-01'
        actual = T.natural_episode(127433440, source / 'model.pt', T.S.sha(source / 'model.pt'),
                                   T.H.read_json(source / 'config.json'))
        expected = T.H.read_json(source / 'episodes/127433440.json.gz')
        self.assertEqual(actual['prefix'], expected['prefix'])
        self.assertEqual(T.P.terminal_signature(actual), T.P.terminal_signature(expected))
        self.assertTrue(T.valid_episode(actual, 127433440, T.S.sha(source / 'model.pt')))


if __name__ == '__main__':
    unittest.main()
