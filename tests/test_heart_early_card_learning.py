"""Card-first credit assignment, complete trees and deployment boundaries."""
import copy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import test_heart_relic_card_training as F
import heart_early_card_learning as N

torch, R = N.torch, N.R


def fixture():
    old, states, _, refs, rs, cs = F.fixture()
    card = dict(states['a'], prefix_index=1)
    branches = []
    for choice in (0, 1):
        boss = dict(copy.deepcopy(old[0]['boss_root']), id=f'boss-after-{choice}',
                    prefix_index=20, early_card_candidate=choice)
        branches.append({'card_candidate': choice, 'parent_target': 0,
            'boss_root': boss, 'leaves': [{'candidate': c, 'target': int(choice == c == 1)} for c in (0, 1)]})
    return [{'seed': 11, 'card_root': card, 'branches': branches}], refs, rs, cs


class EarlyCardLearningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.base = torch.load(Path(os.environ['HEART_BRANCH_RUNTIME'])/'model.pt',
                              weights_only=True, map_location='cpu')

    def test_exact_expectation_uses_branch_local_relic_policy_and_full_denominator(self):
        values = fixture(); data = N.pack(*values)
        policy = N.EarlyCardPolicy(N.artifact_for(self.base, *values[2:], {}))
        self.assertAlmostEqual(float(N.mean_terminal_return(policy, data).detach()),
                               (1/(1+torch.e))**2/2)
        # Relic-fixed cannot access the joint-only winner, despite its presence
        # in the complete tree. A hindsight max target would fail this test.
        policy = N.EarlyCardPolicy(N.artifact_for(self.base, *values[2:], {}, relic=False))
        self.assertEqual(float(N.mean_terminal_return(policy, data).detach()), 0.)
        branches = values[0][0]['branches']
        branches[0]['boss_root'] = None; branches[0]['leaves'] = []
        data = N.pack(*values)
        self.assertEqual(N.deterministic_outcomes(policy, data)[0]['target'], 0)

    def test_toy_joint_learning_and_checkpoint_roundtrip_preserve_parent_encoder(self):
        values = fixture(); data = N.pack(*values)
        artifact = N.artifact_for(self.base, *values[2:], {})
        policy, _ = N.fit(artifact, data, {'steps':180,'learning_rate':.03,'gradient_norm':1.,'l2':.0001})
        chosen = N.deterministic_outcomes(policy, data)
        self.assertEqual([r['target'] for r in chosen], [1, 0])
        self.assertEqual((chosen[0]['card_candidate'], chosen[0]['relic']['root_id'],
                          chosen[0]['relic']['candidate']), (1, 'boss-after-1', 1))
        loaded = N.EarlyCardPolicy(N.checkpoint(policy, artifact, 180))
        self.assertEqual(N.deterministic_outcomes(loaded, data), chosen)
        parent = N.H.load_scorer(self.base)
        self.assertTrue(all(torch.equal(v, policy.base.state_dict()[k]) for k,v in parent.state_dict().items()))
        self.assertTrue(all(not p.requires_grad and p.grad is None for p in policy.base.parameters()))

    def test_missing_leaf_wrong_role_wrong_parent_and_shared_boss_reject(self):
        for case in ('missing_leaf','role','parent','shared','branch'):
            values = fixture(); tree=values[0][0]
            if case=='missing_leaf':tree['branches'][1]['leaves'].pop()
            elif case=='role':tree['branches'][1]['boss_root']['split']='label_holdout'
            elif case=='parent':values[1][0]['status']='heart_win'
            elif case=='shared':tree['branches'][1]['boss_root']['id']='boss-after-0'
            else:tree['branches'][1]['boss_root']['early_card_candidate']=0
            with self.subTest(case=case), self.assertRaises(ValueError):N.pack(*values)

    def test_unknown_card_offer_falls_back_without_nan_or_validation_scaling(self):
        values=fixture(); fit=N.pack(*values)
        policy=N.EarlyCardPolicy(N.artifact_for(self.base,values[2],[values[3][0]],{}))
        validation=N.pack(*values[:3],[values[3][0]])
        before=policy.card.scale.clone()
        loss,reward=N.objective(policy,validation,.001);loss.backward()
        self.assertEqual(float(reward.detach()),0.)
        self.assertTrue(torch.equal(before,policy.card.scale))
        self.assertTrue(all(p.grad is None or torch.isfinite(p.grad).all() for p in policy.parameters()))
        self.assertEqual([r['target'] for r in N.deterministic_outcomes(policy,validation)],[0,0])

    def test_later_menu_cannot_change_earlier_scores_with_fixed_weights(self):
        values=fixture();data=N.pack(*values)
        policy=N.EarlyCardPolicy(N.artifact_for(self.base,*values[2:],{}))
        with torch.no_grad():policy.card.weight.fill_(.3)
        before=policy.training_logits(data)[1].clone()
        for b in values[0][0]['branches']:b['boss_root']['observation']=[[0,99.]]
        changed=N.pack(*values)
        self.assertTrue(torch.equal(before,policy.training_logits(changed)[1]))

    def test_early_card_predicate_excludes_act_two_and_earlier_prayer_wheel_offer(self):
        tree=fixture()[0][0];desc=[R.dense(d,N.A.DESC_DIM) for d in tree['card_root']['descriptors']]
        gc=SimpleNamespace(act=1,cur_map_node_y=0,cur_room=R.sts.Room.MONSTER,
            screen_state=R.sts.ScreenState.REWARDS,rewards={'cards':[[]]})
        self.assertTrue(N.card_eligible(gc,desc,0))
        gc.act=2;self.assertFalse(N.card_eligible(gc,desc,0))
        gc.act=1;gc.rewards['cards'].append([]);self.assertFalse(N.card_eligible(gc,desc,0))


if __name__ == '__main__':unittest.main()
