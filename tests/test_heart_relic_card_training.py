"""Check joint credit and complete-family accounting against small exact trees."""
import copy
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_relic_card_training as L

H, R, A, J = L.H, L.R, L.A, L.J
torch = H.torch


def state(seed, name, stage, identities, chosen=0, hp=.7):
    descriptors = []
    for identity in identities:
        d = [0.] * A.DESC_DIM
        d[A.OFF_ACTION + (A.AK_BOSS_RELIC if stage == 'relic' else A.AK_REWARD_CARD)] = 1.
        d[(A.OFF_RELIC if stage == 'relic' else A.OFF_CARD) + identity] = 1.
        descriptors.append(R.sparse(d))
    obs = [0.] * A.OBS_DIM
    obs[0], obs[1], obs[4] = hp, .8, .25 if stage == 'relic' else .5
    return {'id': name, 'seed': seed, 'split': 'fit', 'candidates': list(range(len(identities))),
            'chosen': chosen, 'option_ids': identities, 'observation': R.sparse(obs), 'descriptors': descriptors}


def fixture():
    # These are analytic terminal labels, not empirical game results.
    relics = [int(R.sts.RelicId.BLACK_BLOOD), int(R.sts.RelicId.ECTOPLASM)]
    cards = [int(R.sts.CardId.SHRUG_IT_OFF), int(R.sts.CardId.SEEING_RED)]
    boss = state(11, 'boss', 'relic', relics)
    a = dict(state(11, 'a', 'card', cards, hp=.4), relic_candidate=0)
    b = dict(state(11, 'b', 'card', cards, hp=.8), relic_candidate=1)
    tree = {'seed': 11, 'chosen': 0, 'boss_root': boss, 'branches': [
        {'relic_candidate': 0, 'card_root': 'a', 'parent_target': 0.},
        {'relic_candidate': 1, 'card_root': 'b', 'parent_target': 0.}]}
    labels = {'a': [{'candidate': 0, 'target': 0.}, {'candidate': 1, 'target': 0.}],
              'b': [{'candidate': 0, 'target': 0.}, {'candidate': 1, 'target': 1.}]}
    references = [{'seed': 11, 'split': 'fit', 'status': 'death'},
                  {'seed': 22, 'split': 'fit', 'status': 'death'}]
    return [tree], {'a': a, 'b': b}, labels, references, relics, cards


class JointTrainingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        runtime = Path(os.environ['HEART_BRANCH_RUNTIME'])
        cls.base = torch.load(runtime / 'model.pt', weights_only=True, map_location='cpu')

    def policy(self, relic=True, card=True, supports_=None):
        *_, relics, cards = fixture()
        if supports_ is not None: cards = supports_
        return J.RelicCardPolicy({'model_type': J.RelicCardPolicy.model_type,
            'base_checkpoint': self.base, 'relic_support': relics, 'card_support': cards,
            'change_relic': relic, 'change_card': card})

    def test_joint_expectation_includes_early_death_in_family_denominator(self):
        data = L.pack(*fixture())
        policy = self.policy()
        # One success among four equiprobable paths for one of two families.
        self.assertAlmostEqual(float(L.mean_terminal_return(policy, data).detach()), .125)
        for flags in ((True, False), (False, True)):
            self.assertEqual(float(L.mean_terminal_return(self.policy(*flags), data).detach()), 0.)
        result = L.deterministic_outcomes(policy, data)
        self.assertEqual([r['target'] for r in result], [0, 0])
        self.assertTrue(result[1]['no_intervention'])
        self.assertEqual(result[0]['relic_candidate'], 0)

    def test_parameter_learning_finds_joint_winner_and_preserves_early_failure(self):
        torch.manual_seed(91)
        data, policy = L.pack(*fixture()), self.policy()
        optimizer = torch.optim.Adam([p for p in policy.parameters() if p.requires_grad], lr=.02)
        for _ in range(200):
            loss, _ = L.objective(policy, data, .001)
            optimizer.zero_grad(); loss.backward(); optimizer.step()
        self.assertGreater(float(L.mean_terminal_return(policy, data).detach()), .45)
        outcomes = L.deterministic_outcomes(policy, data)
        self.assertEqual([r['target'] for r in outcomes], [1, 0])
        self.assertEqual(outcomes[0]['relic_candidate'], 1)
        self.assertEqual(outcomes[0]['card'], {'root_id': 'b', 'candidate': 1})

    def test_incomplete_leaves_and_cross_role_families_are_rejected(self):
        for mutation in ('missing_leaf', 'null_target', 'missing_relic', 'cross_role', 'wrong_parent'):
            values = copy.deepcopy(fixture())
            trees, states, labels, refs, *_ = values
            if mutation == 'missing_leaf': labels['b'].pop()
            elif mutation == 'null_target': labels['b'][1]['target'] = None
            elif mutation == 'missing_relic': trees[0]['branches'].pop()
            elif mutation == 'cross_role': states['b']['split'] = 'label_holdout'
            else: refs[0]['status'] = 'heart_win'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                L.pack(*values)

    def test_unknown_offer_uses_parent_and_does_not_create_nan_gradients(self):
        values = fixture()
        restricted = [values[-1][0]]
        data = L.pack(*values[:-1], restricted)
        policy = self.policy(supports_=restricted)
        loss, expected = L.objective(policy, data, .001)
        self.assertEqual(float(expected.detach()), 0.)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        for parameter in policy.parameters():
            if parameter.grad is not None:
                self.assertTrue(torch.isfinite(parameter.grad).all())
        self.assertEqual([r['target'] for r in L.deterministic_outcomes(policy, data)], [0, 0])

    def test_terminal_before_card_keeps_its_observed_outcome(self):
        trees, states, labels, refs, relics, cards = copy.deepcopy(fixture())
        trees[0]['branches'][1].update(card_root=None, parent_target=1.)
        del states['b']; del labels['b']
        data = L.pack(trees, states, labels, refs, relics, cards)
        policy = self.policy()
        self.assertAlmostEqual(float(L.mean_terminal_return(policy, data).detach()), .25)
        with torch.no_grad(): policy.relic.static_scores[1] = 10
        choice = L.deterministic_outcomes(policy, data)[0]
        self.assertEqual(choice['target'], 1)
        self.assertIsNone(choice['card'])

    def test_label_order_does_not_change_the_learning_target(self):
        values = copy.deepcopy(fixture())
        a = L.pack(*values)
        values[0][0]['branches'].reverse()
        for leaves in values[2].values(): leaves.reverse()
        b = L.pack(*values)
        policy = self.policy()
        self.assertTrue(torch.equal(L.mean_terminal_return(policy, a), L.mean_terminal_return(policy, b)))
        self.assertEqual(L.deterministic_outcomes(policy, a), L.deterministic_outcomes(policy, b))


if __name__ == '__main__':
    unittest.main()
