"""Intervention labels require frozen-policy continuation and natural replay."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
import heart_branch_pilot as P


class BranchPilotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        P.H.torch.set_num_threads(1)
        cls.source = REPO / 'runs/heart-training-set-evaluation-20260915-01'
        cls.config = P.H.read_json(cls.source / 'config.json')
        cls.episode = P.H.read_json(cls.source / 'episodes/127433440.json.gz')
        cls.net = P.H.load_scorer(P.H.torch.load(cls.source / 'model.pt', map_location='cpu', weights_only=True))
        eligible = P.eligible_roots(cls.episode, cls.config, 33)
        # A late real root bounds test compute without changing the combat budget.
        cls.root = next(r for r in reversed(eligible) if r['category'] != 'card_select')
        cls.root.update(id='test-root', split='fit', stratum='test', candidates=[])
        cls.root['candidates'] = P.select_candidates(cls.root, random.Random(17))

    def test_candidates_preserve_neural_and_live_heuristic_actions(self):
        root = {'chosen': 7, 'teacher': 1, 'eligible': [3, 4, 5, 6, 7]}
        chosen = P.select_candidates(root, random.Random(17))
        self.assertEqual(chosen[:2], [7, 1])
        self.assertEqual(len(set(chosen)), 4)
        self.assertTrue(set(chosen[2:]) <= set(root['eligible']))

    def test_public_training_and_live_inference_scores_match(self):
        scores = P.check_encoding(self.root, self.net)
        self.assertEqual(max(range(len(scores)), key=scores.__getitem__), self.root['chosen'])

    def test_original_action_replans_to_identical_natural_terminal(self):
        result = P.execute_branch(self.episode, self.root, self.root['chosen'], self.config, self.net)
        self.assertTrue(result['original_control_matches'])
        self.assertEqual(result['prefix'], self.episode['prefix'])
        self.assertEqual(P.terminal_signature(result), P.terminal_signature(self.episode))
        self.assertEqual(result['simulations'], self.episode['simulations'])

    def test_explicit_neural_continuation_and_replay_verified_alternative(self):
        selected = next(i for i in self.root['candidates'] if i != self.root['chosen'])
        actual_rollout = P.R.rollout

        def require_policy(*args, **kwargs):
            # An omitted net invokes the old heuristic, invalidating the experiment.
            if kwargs.get('net') is not self.net:
                raise AssertionError('continuation policy was not explicitly retained')
            return actual_rollout(*args, **kwargs)

        with patch.object(P.R, 'rollout', side_effect=require_policy):
            result = P.execute_branch(self.episode, self.root, selected, self.config, self.net)
        self.assertIsNotNone(P.R.target(result['status']), result)
        self.assertTrue(result['replay_verified'])
        self.assertEqual(result['prefix'][self.root['prefix_index']]['action'], self.root['actions'][selected])
        self.assertNotEqual(result['prefix'], self.episode['prefix'])
        restored = P.R.replay(result['seed'], result['prefix'], self.config)
        P.verify_terminal(restored, result)

    def test_restore_rejects_changed_rng_fingerprint_or_candidate_order(self):
        for field, changed in [('fingerprint', 'corrupt'), ('actions', list(reversed(self.root['actions'])))]:
            root = {**self.root, field: changed}
            with self.assertRaisesRegex(ValueError, 'RNG|mapping'):
                P.execute_branch(self.episode, root, root['chosen'], self.config, self.net)

    def test_fault_or_unverified_control_cannot_be_zero_or_preference_label(self):
        candidate = self.root['chosen']
        good = {'seed': self.root['seed'], 'root_id': self.root['id'], 'candidate': candidate,
                'action': self.root['actions'][candidate], 'checkpoint_sha256': 'test',
                'status': 'death', 'target': 0.0, 'replay_verified': True,
                'terminal_state_verified': True, 'terminal_fingerprint': 'present',
                'prefix': [1], 'original_control_matches': True}
        self.assertTrue(P.qualified(good, self.root, candidate, 'test'))
        for status in ('truncated', 'timeout', 'execution_error', 'control_mismatch'):
            self.assertFalse(P.qualified({**good, 'status': status}, self.root, candidate, 'test'))
        self.assertFalse(P.qualified({**good, 'original_control_matches': False}, self.root, candidate, 'test'))
        self.assertFalse(P.qualified({**good, 'action': -1}, self.root, candidate, 'test'))

    def test_root_families_do_not_overlap_or_use_validation_seeds(self):
        roles = {'train': [1, 2], 'validation': [3], 'selected_development': [3], 'final_test': [4]}
        good = [{'seed': 1, 'split': 'fit'}, {'seed': 2, 'split': 'label_holdout'}]
        P.validate_root_roles(good, roles)
        for bad in ([good[0], {**good[1], 'seed': 1}], [good[0], {**good[1], 'seed': 3}]):
            with self.assertRaisesRegex(ValueError, 'root'):
                P.validate_root_roles(bad, roles)

    def test_ranking_gradient_prefers_winner_without_relabelling_teacher(self):
        score = P.H.torch.tensor([0.0, 2.0, 0.0], requires_grad=True)
        # Baseline/prior points to index 1; the intervention made index 2 win.
        loss = P.preference_loss(score, [0.0, 1.0], [1, 2])
        loss.backward()
        self.assertGreater(float(score.grad[1]), 0)
        self.assertLess(float(score.grad[2]), 0)
        self.assertEqual(float(score.grad[0]), 0)
        with self.assertRaisesRegex(ValueError, 'both outcomes'):
            P.preference_loss(score, [0.0, 0.0], [1, 2])


if __name__ == '__main__':
    unittest.main()
