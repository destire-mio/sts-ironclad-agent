"""Full-run learning contracts plus a natural simulator episode."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
runtime = json.loads((ROOT / '.runtime/runtime.json').read_text(encoding='utf-8'))
os.environ['STS_LIGHTSPEED_BUILD'] = str(Path(runtime['module']).parent)
sys.path.insert(0, str(ROOT / 'agent'))
import torch
torch.set_num_threads(1)
import heart_runtime as R
import heart_fullrun_train as T
from heart_fullrun_policy import FullRunPolicy, EpisodePolicy, advantages, ppo_loss


class FullRunContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = T.H.read_json(ROOT / 'configs/fullrun_smoke.json')
        cls.parent = T.load(T.PARENT)
        torch.manual_seed(cls.config['model_seed'])
        cls.policy = FullRunPolicy(cls.parent, cls.config)
        cls.collector = EpisodePolicy(cls.policy, 9012345, False)
        game = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, 9012345, 20)
        cls.episode = R.rollout(9012345, cls.config, gc=game, net=cls.collector,
                               record=True, record_samples=False)
        R.clock_input(game, cls.config)
        cls.episode.update(decisions=cls.collector.rows, terminal_fingerprint=R.fingerprint(game))
        cls.episode['verified_decisions'] = T.verify_episode(cls.episode, cls.policy, cls.config)
        cls.episode['replay_verified'] = True

    def test_terminal_credit_uses_heart_outcome_and_no_floor_bonus(self):
        a, targets = advantages([.2, .3], 1., lam=1.)
        self.assertAlmostEqual(a[0], .8)
        self.assertAlmostEqual(a[1], .7)
        self.assertEqual(targets, [1., 1.])
        _, targets = advantages([.2, .3], 0., lam=1.)
        self.assertEqual(targets, [0., 0.])
        with self.assertRaises(ValueError):
            advantages([.2], None)

    def test_ppo_clips_improvements_but_retains_bad_action_penalty(self):
        old = torch.tensor([-.7])
        high = old + math.log(2)
        self.assertAlmostEqual(float(ppo_loss(high, old, torch.ones(1), .2)), -1.2, places=5)
        self.assertAlmostEqual(float(ppo_loss(high, old, -torch.ones(1), .2)), 2., places=5)
        self.assertAlmostEqual(float(ppo_loss(old + math.log(.5), old, -torch.ones(1), .2)), .8, places=5)

    def test_initial_greedy_policy_matches_parent_along_natural_route(self):
        self.assertGreater(len(self.collector.rows), 3)
        self.assertTrue(all(r['chosen'] == r['teacher'] for r in self.collector.rows))
        self.assertGreater(len({r['action_kind'] for r in self.collector.rows}), 2)
        self.assertIn(self.episode['status'], ('death', 'heart_win', 'act3_without_heart'))

    def test_real_game_state_and_rng_replay_and_corruption_rejected(self):
        self.assertEqual(T.verify_episode(self.episode, self.policy, self.config), len(self.collector.rows))
        bad = copy.deepcopy(self.episode)
        bad['terminal_fingerprint'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'terminal state'):
            T.verify_episode(bad, self.policy, self.config)

    def test_fault_and_tampered_likelihood_rejected(self):
        bad = copy.deepcopy(self.episode)
        bad.update(status='execution_error', target=None)
        with self.assertRaisesRegex(ValueError, 'faults'):
            T.verify_episode(bad, self.policy, self.config)
        bad = copy.deepcopy(self.episode)
        bad['decisions'][0]['old_log_prob'] += .1
        with self.assertRaisesRegex(ValueError, 'likelihood'):
            T.verify_episode(bad, self.policy, self.config)

    def test_exploration_uses_separate_reproducible_generator(self):
        game = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, 9012345, 20)
        actions = list(R.sts.get_legal_game_actions(game))
        _, descriptors, _ = T.H.A.build_choices(game)
        one = EpisodePolicy(self.policy, 771, True)
        two = EpisodePolicy(self.policy, 771, True)
        before = R.fingerprint(game)
        obs = T.H.A.obs_vec(game)
        a = [one.choose(game, obs, actions, descriptors) for _ in range(12)]
        b = [two.choose(game, obs, actions, descriptors) for _ in range(12)]
        self.assertEqual(a, b)
        self.assertEqual(before, R.fingerprint(game))
        self.assertTrue(all(0 <= x < len(actions) for x in a))

    def test_seed_roles_and_rounds_are_disjoint_and_exclude_history(self):
        excluded = {9012345, 8123}
        config = dict(self.config, iterations=3, episodes_per_iteration=5, acceptance_seeds=9)
        plan = T.seed_plan(config, excluded)
        all_seeds = sum(plan.values(), [])
        self.assertEqual(plan, T.seed_plan(config, excluded))
        self.assertEqual(len(all_seeds), len(set(all_seeds)))
        self.assertFalse(excluded.intersection(all_seeds))
        self.assertEqual(len(plan['train']), 15)

    def test_optimizer_updates_backbone_and_preserves_reference(self):
        policy = FullRunPolicy(self.parent, self.config, self.policy.snapshot())
        actor_before = policy.actor.net[0].weight.detach().clone()
        reference_before = {k: v.clone() for k, v in policy.reference.state_dict().items()}
        optimizer = torch.optim.Adam([p for p in policy.parameters() if p.requires_grad], lr=.00003)
        report = T.fit(policy, optimizer, [copy.deepcopy(self.episode)], self.config, 1)
        self.assertGreater(report['updates'], 0)
        self.assertFalse(torch.equal(actor_before, policy.actor.net[0].weight))
        self.assertTrue(all(torch.equal(v, policy.reference.state_dict()[k]) for k, v in reference_before.items()))
        restored = FullRunPolicy(self.parent, self.config, policy.snapshot())
        logits, values = policy.forward_rows(self.collector.rows[:2])
        restored_logits, restored_values = restored.forward_rows(self.collector.rows[:2])
        self.assertTrue(torch.equal(values, restored_values))
        self.assertTrue(all(torch.equal(a, b) for a, b in zip(logits, restored_logits)))

    def test_stale_batch_never_updates_model(self):
        policy = FullRunPolicy(self.parent, self.config, self.policy.snapshot())
        optimizer = torch.optim.Adam([p for p in policy.parameters() if p.requires_grad], lr=.00003)
        bad = copy.deepcopy(self.episode)
        bad['decisions'][0]['old_log_prob'] += .5
        before = policy.actor.net[0].weight.detach().clone()
        with self.assertRaisesRegex(ValueError, 'stale'):
            T.fit(policy, optimizer, [bad], self.config, 1)
        self.assertTrue(torch.equal(before, policy.actor.net[0].weight))


if __name__ == '__main__':
    unittest.main()
