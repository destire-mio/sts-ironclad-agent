"""Joint credit, causal inputs, and two self-terminating native choices."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

AGENT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT))
import heart_branch_training as T
import heart_relic_card_model as J
import heart_relic_card_pilot as Pilot

H, R, A, P = T.H, T.R, T.H.A, T.P


class RelicCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.torch.set_num_threads(1)
        cls.runtime = Path(os.environ['HEART_BRANCH_RUNTIME']).resolve()
        cls.base = H.torch.load(cls.runtime / 'model.pt', weights_only=True, map_location='cpu')
        cls.config = H.read_json(cls.runtime / 'config.json')
        cls.row = H.read_json(cls.runtime / 'episodes/1706559026.json.gz')

    def artifact(self):
        return {'model_type': J.RelicCardPolicy.model_type, 'base_checkpoint': self.base,
                'relic_support': self.base['support'], 'card_support': list(range(A.CARD_CAP + 2)),
                'change_relic': True, 'change_card': True}

    def test_zero_heads_preserve_complete_native_route_and_repeated_queries(self):
        policy = J.RelicCardPolicy(self.artifact())
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, self.row['seed'], 20)
        counts = [0, 0]
        for step in self.row['prefix']:
            R.clock_input(gc, self.config)
            if step['kind'] == 'outside':
                actions = list(R.sts.get_legal_game_actions(gc))
                _, desc, _ = A.build_choices(gc)
                with H.torch.no_grad():
                    selected = policy.choose(gc, A.obs_vec(gc), actions, desc)
                    self.assertEqual(selected, policy.choose(gc, A.obs_vec(gc), actions, desc))
                self.assertEqual(int(actions[selected].bits), step['action'])
                counts[0] += J.relic_eligible(gc, desc, selected)
                counts[1] += J.card_eligible(gc, desc, selected)
            R.replay_step(gc, step, self.config)
        R.clock_input(gc, self.config)
        P.verify_terminal(gc, self.row)
        self.assertEqual(counts, [1, 1])

    def test_card_change_ends_after_consuming_offer_and_unknown_offer_falls_back(self):
        policy = J.RelicCardPolicy(self.artifact())
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, self.row['seed'], 20)
        for step in self.row['prefix']:
            R.clock_input(gc, self.config)
            if step['kind'] == 'outside':
                actions = list(R.sts.get_legal_game_actions(gc))
                _, desc, _ = A.build_choices(gc)
                with H.torch.no_grad(): baseline = policy.base.choose(gc, A.obs_vec(gc), actions, desc)
                if J.card_eligible(gc, desc, baseline):
                    alternative = next(i for i, d in enumerate(desc)
                        if J.card_option(d) is not None and i != baseline)
                    identity = J.card_option(desc[alternative])
                    with H.torch.no_grad():
                        policy.card.static_scores[policy.card_positions[identity]] = 1000
                        self.assertEqual(policy.choose(gc, A.obs_vec(gc), actions, desc), alternative)
                        self.assertEqual(policy.choose(gc, A.obs_vec(gc), actions, desc), alternative)
                    artifact = self.artifact()
                    artifact['card_support'].remove(identity)
                    unsupported = J.RelicCardPolicy(artifact)
                    with H.torch.no_grad():
                        self.assertEqual(unsupported.choose(gc, A.obs_vec(gc), actions, desc), baseline)
                    actions[alternative].execute(gc)
                    actions = list(R.sts.get_legal_game_actions(gc))
                    _, desc, _ = A.build_choices(gc)
                    with H.torch.no_grad():
                        parent = policy.base.choose(gc, A.obs_vec(gc), actions, desc)
                        self.assertFalse(J.card_eligible(gc, desc, parent))
                        self.assertEqual(policy.choose(gc, A.obs_vec(gc), actions, desc), parent)
                    return
            R.replay_step(gc, step, self.config)
        self.fail('fixture has no eligible card reward')

    def test_tree_expectation_matches_explicit_paths_and_frozen_arms(self):
        r = H.torch.tensor([[.3, -.2, float('-inf')]], requires_grad=True)
        c = H.torch.tensor([[.8, -.1], [-.4, .6]], requires_grad=True)
        y = H.torch.tensor([[0., 1.], [1., 0.]])
        indices, terminals = H.torch.tensor([[0, 1, -1]]), H.torch.zeros((1, 3))
        observed = J.expected_returns(r, c, y, indices, terminals)
        rp, cp = r.softmax(-1), c.softmax(-1)
        self.assertTrue(H.torch.allclose(observed, rp[:, 0] * cp[0, 1] + rp[:, 1] * cp[1, 0]))
        frozen_r = J.expected_returns(r, c, y, indices, terminals, relic_baseline=H.torch.tensor([1]))
        self.assertTrue(H.torch.allclose(frozen_r, cp[1, 0]))
        frozen_c = J.expected_returns(r, c, y, indices, terminals, card_baseline=H.torch.tensor([0, 1]))
        self.assertEqual(float(frozen_c), 0.)
        observed.sum().backward()
        self.assertEqual(float(r.grad[0, 2]), 0.)
        self.assertTrue(H.torch.isfinite(c.grad).all())

    def test_joint_credit_finds_combination_invisible_to_either_single_change(self):
        # Parent takes relic0/card0. Only relic1 followed by card1 succeeds.
        r = H.torch.nn.Parameter(H.torch.zeros((1, 2)))
        c = H.torch.nn.Parameter(H.torch.zeros((2, 2)))
        y = H.torch.tensor([[0., 0.], [0., 1.]])
        indices, terminals = H.torch.tensor([[0, 1]]), H.torch.zeros((1, 2))
        self.assertEqual(float(J.expected_returns(r, c, y, indices, terminals,
            relic_baseline=H.torch.tensor([0]))), 0.)
        self.assertEqual(float(J.expected_returns(r, c, y, indices, terminals,
            card_baseline=H.torch.tensor([0, 0]))), 0.)
        optimizer = H.torch.optim.Adam([r, c], lr=.1)
        for _ in range(120):
            loss = -J.expected_returns(r, c, y, indices, terminals).mean()
            optimizer.zero_grad(); loss.backward(); optimizer.step()
        self.assertGreater(float(J.expected_returns(r, c, y, indices, terminals)), .99)
        self.assertEqual(int(r.argmax(-1)[0]), 1)
        self.assertEqual(int(c[1].argmax()), 1)

    def test_uniform_terminal_labels_do_not_invent_preferences(self):
        for target in (0., 1.):
            r = H.torch.randn((2, 2), requires_grad=True)
            c = H.torch.randn((4, 3), requires_grad=True)
            value = J.expected_returns(r, c, H.torch.full((4, 3), target),
                H.torch.tensor([[0, 1], [2, 3]]), H.torch.zeros((2, 2))).mean()
            value.backward()
            self.assertTrue(H.torch.allclose(r.grad, H.torch.zeros_like(r), atol=1e-7))
            self.assertTrue(H.torch.allclose(c.grad, H.torch.zeros_like(c), atol=1e-7))

    def test_production_loader_preserves_both_trained_heads(self):
        spec = importlib.util.spec_from_file_location('production_joint_loader', AGENT / 'heart_train.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        artifact = self.artifact(); policy = J.RelicCardPolicy(artifact)
        with H.torch.no_grad():
            policy.card.static_scores.fill_(2.5)
            policy.relic.static_scores.fill_(-1.5)
        artifact.update(relic_state=policy.relic.state_dict(), card_state=policy.card.state_dict())
        loaded = module.load_scorer(artifact)
        self.assertTrue(H.torch.equal(loaded.card.static_scores, policy.card.static_scores))
        self.assertTrue(H.torch.equal(loaded.relic.static_scores, policy.relic.static_scores))


if __name__ == '__main__':
    unittest.main()
