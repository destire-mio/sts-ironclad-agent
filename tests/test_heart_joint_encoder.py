"""Encoder-copy isolation and terminal-tree learning, with analytic fixtures."""
import copy
import math
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_joint_encoder as M

x, helper = M.components(Path(os.environ['HEART_BRANCH_RUNTIME']))
import test_heart_relic_card_training as fixtures
torch = M.torch


def data(support=None):
    trees, states, labels, references, *_ = fixtures.fixture()
    bundle = dict(trees=trees, states=states, labels=labels, references=references)
    packed, support = M.pack(helper, bundle, references, support)
    M.add_features(M.JointEncoderPolicy(x, support, 'frozen'), packed)
    return packed, support


class EncoderCopyTests(unittest.TestCase):
    def test_initial_arms_agree_and_complete_tree_expectation_is_exact(self):
        packed, support = data()
        models = [M.JointEncoderPolicy(x, support, arm) for arm in M.ARMS]
        for model in models:
            model.fit_scales(packed)
            # Only second relic -> second card wins; a second family died early.
            self.assertAlmostEqual(float(M.objective(model, packed)[1].detach()), 1/(1+math.e)**2/2, places=12)
            self.assertEqual(M.outcomes(model, packed)['targets'], {11: 0, 22: 0})
        for a, b in zip(models[0].training_logits(packed), models[1].training_logits(packed)):
            self.assertTrue(torch.equal(a, b))
        self.assertFalse(models[0].encoder_weight.requires_grad)
        self.assertTrue(models[1].encoder_weight.requires_grad)

    def test_sparse_and_dense_values_and_gradients_agree(self):
        packed, support = data(); model = M.JointEncoderPolicy(x, support, 'trainable')
        matrix = packed['card']['encoder_features']
        sparse = model.encode(matrix); dense = model.encode(matrix.to_dense())
        torch.testing.assert_close(sparse, dense, rtol=1e-12, atol=1e-12)
        a = torch.autograd.grad(sparse.square().sum(), (model.encoder_weight, model.encoder_bias))
        b = torch.autograd.grad(dense.square().sum(), (model.encoder_weight, model.encoder_bias))
        for left, right in zip(a, b): torch.testing.assert_close(left, right, rtol=1e-11, atol=1e-11)

    def test_learning_changes_copy_and_joint_actions_without_changing_parent(self):
        packed, support = data(); model = M.JointEncoderPolicy(x, support, 'trainable')
        original = {key: value.clone() for key, value in model.base.state_dict().items()}
        self.assertNotEqual(model.encoder_weight.data_ptr(), model.base.base.net[0].weight.data_ptr())
        M.fit(model, packed, 100)
        self.assertFalse(torch.equal(model.encoder_weight, model.initial_weight))
        self.assertEqual(M.outcomes(model, packed)['targets'], {11: 1, 22: 0})
        self.assertEqual(M.outcomes(model, packed)['choices'][0]['relic'], 1)
        self.assertEqual(M.outcomes(model, packed)['choices'][0]['card'], 1)
        for key, value in model.base.state_dict().items(): self.assertTrue(torch.equal(value, original[key]))
        self.assertTrue(all(not p.requires_grad and p.grad is None for p in model.base.parameters()))
        loaded = M.JointEncoderPolicy(x, support, 'trainable', model.learned_state())
        self.assertEqual(M.outcomes(model, packed), M.outcomes(loaded, packed))

    def test_frozen_control_learns_heads_but_preserves_encoder(self):
        packed, support = data(); model = M.JointEncoderPolicy(x, support, 'frozen')
        M.fit(model, packed, 100)
        self.assertEqual(M.outcomes(model, packed)['targets'], {11: 1, 22: 0})
        self.assertTrue(torch.equal(model.encoder_weight, model.initial_weight))
        self.assertTrue(torch.equal(model.encoder_bias, model.initial_bias))

    def test_unknown_offer_falls_back_with_finite_gradients(self):
        _, support = data(); support['card'] = support['card'][:1]
        packed, support = data(support); model = M.JointEncoderPolicy(x, support, 'trainable')
        model.fit_scales(packed)
        loss, expected = M.objective(model, packed); loss.backward()
        self.assertEqual(float(expected.detach()), 0)
        self.assertTrue(all(p.grad is None or torch.isfinite(p.grad).all() for p in model.parameters()))
        self.assertEqual(M.outcomes(model, packed)['targets'], {11: 0, 22: 0})

    def test_future_card_observation_cannot_change_relic_scores(self):
        packed, support = data(); model = M.JointEncoderPolicy(x, support, 'trainable')
        model.fit_scales(packed)
        with torch.no_grad(): model.heads['relic'].weight.fill_(.1)
        before = model.training_logits(packed)[0].detach().clone()
        packed['card']['encoder_features'] = packed['card']['encoder_features'] * 7
        self.assertTrue(torch.equal(before, model.training_logits(packed)[0]))

    def test_optional_dense_state_features_preserve_all_training_labels(self):
        fixture = fixtures.fixture()
        original = helper.pack(*fixture); lean = helper.pack(*fixture, include_features=False)
        self.assertIsNotNone(original['card']['features']); self.assertIsNone(lean['card']['features'])
        for key in ('labels', 'branch_indices', 'terminals'):
            self.assertTrue(torch.equal(original[key], lean[key]))
        for stage in ('card', 'relic'):
            for key in ('positions', 'mask', 'extras', 'baseline', 'allowed'):
                self.assertTrue(torch.equal(original[stage][key], lean[stage][key]))

    def test_selection_uses_validation_and_conservative_ties(self):
        curve = [dict(step=0, validation_wins=10, validation_changes=0),
                 dict(step=100, validation_wins=12, validation_changes=4),
                 dict(step=250, validation_wins=12, validation_changes=3),
                 dict(step=500, validation_wins=12, validation_changes=3)]
        self.assertEqual(M.select_steps(curve, 10), 250)
        self.assertEqual(M.select_steps(curve, 12), 0)
        self.assertEqual(M.choose_index([1, 1+1e-10, 0], 0), 0)
        self.assertEqual(M.choose_index([2, 2, 1], 2), 0)

    def test_invalid_arm_support_or_checkpoint_rejected(self):
        _, support = data()
        with self.assertRaises(ValueError): M.JointEncoderPolicy(x, support, 'typo')
        invalid = copy.deepcopy(support); invalid['card'].append(invalid['card'][0])
        with self.assertRaises(ValueError): M.JointEncoderPolicy(x, invalid, 'frozen')
        state = M.JointEncoderPolicy(x, support, 'frozen').learned_state()
        state['heads']['card.scale'][0] = 0
        with self.assertRaises(ValueError): M.JointEncoderPolicy(x, support, 'frozen', state)


if __name__ == '__main__': unittest.main()
