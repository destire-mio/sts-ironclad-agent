"""Scoped learning behavior, public-state boundaries and native route controls."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

AGENT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT))
import heart_branch_training as T
import heart_contextual_relic as M

H, R, A, P = T.H, T.R, T.H.A, T.P


class ContextualRelicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.torch.set_num_threads(1)
        cls.runtime = Path(os.environ['HEART_BRANCH_RUNTIME']).resolve()
        cls.base = H.torch.load(cls.runtime / 'model.pt', weights_only=True, map_location='cpu')
        cls.config = H.read_json(cls.runtime / 'config.json')
        cls.row = H.read_json(cls.runtime / 'episodes/1706559026.json.gz')

    def artifact(self, contextual=True):
        support = self.base['support']
        return {'model_type': M.ContextualRelicPolicy.model_type, 'base_checkpoint': self.base,
                'support': support, 'contextual': contextual,
                'initial_scores': self.base['relic_scores'][support]}

    def test_initialized_policy_replays_parent_full_route_and_rng(self):
        policy = M.ContextualRelicPolicy(self.artifact())
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, self.row['seed'], 20)
        eligible, later = 0, 0
        for step in self.row['prefix']:
            R.clock_input(gc, self.config)
            if step['kind'] == 'outside':
                actions = list(R.sts.get_legal_game_actions(gc))
                _, desc, _ = A.build_choices(gc)
                obs = A.obs_vec(gc)
                with H.torch.no_grad():
                    selected = policy.choose(gc, obs, actions, desc)
                    self.assertEqual(selected, policy.choose(gc, obs, actions, desc))
                self.assertEqual(int(actions[selected].bits), step['action'])
                if M.eligible(gc, desc, selected): eligible += 1
                if gc.act == 2 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS: later += 1
            R.replay_step(gc, step, self.config)
        R.clock_input(gc, self.config)
        P.verify_terminal(gc, self.row)
        self.assertEqual(eligible, 1)
        self.assertGreaterEqual(later, 1)
        self.assertTrue(all(not p.requires_grad for p in policy.base.parameters()))

    def test_hidden_counter_and_map_changes_do_not_enter_features(self):
        x = H.torch.zeros((1, A.OBS_DIM))
        baseline = M.public_features(x)
        changed = x.clone()
        changed[:, 13:32] = 99
        changed[:, 75:M.DECK_OFFSET] = 123
        changed[:, A.BASE_OBS_DIM:] = 234
        self.assertTrue(H.torch.equal(baseline, M.public_features(changed)))
        changed[:, M.DECK_OFFSET] = 1
        self.assertFalse(H.torch.equal(baseline, M.public_features(changed)))

    def test_learned_override_is_once_scoped_and_unknown_offers_fall_back(self):
        policy = M.ContextualRelicPolicy(self.artifact())
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, self.row['seed'], 20)
        second = None
        for index, step in enumerate(self.row['prefix']):
            R.clock_input(gc, self.config)
            if step['kind'] == 'outside' and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS:
                actions = list(R.sts.get_legal_game_actions(gc))
                _, desc, _ = A.build_choices(gc)
                with H.torch.no_grad(): baseline = policy.base.choose(gc, A.obs_vec(gc), actions, desc)
                if gc.act == 1 and M.eligible(gc, desc, baseline):
                    first = index
                    alternative = next(i for i, d in enumerate(desc) if M.option_id(d) is not None and i != baseline)
                    option = M.option_id(desc[alternative])
                    with H.torch.no_grad(): policy.ranker.static_scores[policy.positions[option]] = 1000
                    with H.torch.no_grad():
                        self.assertEqual(policy.choose(gc, A.obs_vec(gc), actions, desc), alternative)
                        self.assertEqual(policy.choose(gc, A.obs_vec(gc), actions, desc), alternative)
                    artifact = self.artifact()
                    keep = [i for i, value in enumerate(artifact['support']) if value != option]
                    artifact['support'] = [artifact['support'][i] for i in keep]
                    artifact['initial_scores'] = artifact['initial_scores'][keep]
                    unsupported = M.ContextualRelicPolicy(artifact)
                    with H.torch.no_grad():
                        self.assertEqual(unsupported.choose(gc, A.obs_vec(gc), actions, desc), baseline)
                if gc.act == 2:
                    with H.torch.no_grad():
                        self.assertEqual(policy.choose(gc, A.obs_vec(gc), actions, desc), baseline)
                    second = index
                    break
            R.replay_step(gc, step, self.config)
        self.assertIsNotNone(second)
        gc = R.replay(self.row['seed'], self.row['prefix'][:first], self.config)
        actions = list(R.sts.get_legal_game_actions(gc))
        actions[alternative].execute(gc)
        actions = list(R.sts.get_legal_game_actions(gc))
        _, desc, _ = A.build_choices(gc)
        with H.torch.no_grad():
            self.assertEqual(policy.choose(gc, A.obs_vec(gc), actions, desc),
                             policy.base.choose(gc, A.obs_vec(gc), actions, desc))

    def test_family_objective_has_equal_weights_and_correct_gradient(self):
        scores = H.torch.tensor([[.8, -.3, .2], [.8, -.3, .2]], requires_grad=True)
        positions, labels = [[0, 1, 2], [0, 1]], [[1, 0, 0], [0, 1]]
        actual = M.family_pair_loss(scores, positions, labels)
        expected = (H.F.softplus(scores[0, 1:] - scores[0, 0]).mean()
                    + H.F.softplus(scores[1, 0] - scores[1, 1])) / 2
        self.assertTrue(H.torch.equal(actual, expected))
        more = H.torch.cat((scores, H.torch.zeros(1, 3)))
        self.assertTrue(H.torch.equal(actual, M.family_pair_loss(more, positions + [[0, 1]], labels + [[0, 0]])))
        actual.backward()
        self.assertLess(scores.grad[0, 0], 0)
        self.assertGreater(scores.grad[1, 0], 0)

    def test_context_can_learn_opposite_choices_with_same_offers(self):
        H.torch.manual_seed(7)
        ranker = M.RelicRanker(H.torch.zeros(2), True)
        x = H.torch.zeros(2, M.FEATURE_DIM)
        x[0, 0], x[1, 1] = 1, 1
        optimizer = H.torch.optim.Adam(ranker.parameters(), lr=.03)
        for _ in range(100):
            loss = M.family_pair_loss(ranker(x), [[0, 1], [0, 1]], [[1, 0], [0, 1]])
            optimizer.zero_grad(); loss.backward(); optimizer.step()
        self.assertEqual(ranker(x).argmax(-1).tolist(), [0, 1])
        self.assertTrue(H.torch.equal(ranker(x[[1, 0]]), ranker(x)[[1, 0]]))

    def test_production_loader_roundtrip_preserves_scores(self):
        artifact = self.artifact()
        policy = M.ContextualRelicPolicy(artifact)
        artifact['ranker_state'] = policy.ranker.state_dict()
        spec = importlib.util.spec_from_file_location('current_heart_loader', AGENT / 'heart_train.py')
        loader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loader)
        loaded = loader.load_scorer(artifact)
        x = H.torch.zeros(3, M.FEATURE_DIM)
        self.assertTrue(H.torch.equal(policy.ranker(x), loaded.ranker(x)))


if __name__ == '__main__':
    unittest.main()
