import copy
import os
from pathlib import Path
import sys
import unittest

import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_offline_control_evaluation as F


class OfflineControlEvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=Path(os.environ['E143_STUDY']);cls.x=F.C.D.runtime(cls.source/'runtime')
        cls.spec=F.E.read(cls.source/'feature-spec.json')
        model=F.O.Actor(cls.spec['width'])
        cls.cp=dict(model_type='observed_control_actor',parent_bonus=3.,arm='cloning',feature_spec=cls.spec,
            actor_state=model.state_dict(),support=[],base_checkpoint=torch.load(cls.source/'runtime/model.pt',
                weights_only=True,map_location='cpu'))
        cls.policy=F.O.ControlPolicy(cls.cp,cls.x)
        refs=F.E.read(cls.source/'fit-references.json')
        cls.refs=refs[:3]+[next(r for r in refs if r['status']=='heart_win')]

    def test_whole_natural_routes_recover_parent_and_verify_full_heart_path(self):
        wins=0
        for ref in self.refs:
            self.assertEqual(F.E.sha(ref['path']),ref['sha256']);row=F.E.read(ref['path'])
            proof=F.audit_route(self.x,row,self.policy,self.cp)
            self.assertEqual(proof['changed_actions_by_kind'],{})
            self.assertEqual(proof['outside_choices'],sum(s['kind']=='outside' for s in row['prefix']))
            self.assertEqual(F.first_change(self.x,row,row),{'kind':'unchanged'})
            if row['status']=='heart_win':
                wins+=1;self.assertEqual(proof['act_four'],['SHIELD_AND_SPEAR','THE_HEART'])
                self.assertEqual(len(set(proof['act_three_bosses'])),2)
        self.assertEqual(wins,1)

    def test_corrupted_rng_action_and_terminal_are_rejected(self):
        original=F.E.read(self.refs[0]['path'])
        wrong=copy.deepcopy(original);wrong['prefix'][0]['before']='incorrect'
        with self.assertRaisesRegex(ValueError,'state/RNG'):F.audit_route(self.x,wrong,self.policy,self.cp)
        wrong=copy.deepcopy(original)
        next(s for s in wrong['prefix'] if s['kind']=='outside')['action']=-98765
        with self.assertRaisesRegex(ValueError,'recorded natural action'):F.audit_route(self.x,wrong,self.policy,self.cp)
        wrong=copy.deepcopy(original);wrong['hp']+=1
        with self.assertRaisesRegex(ValueError,'terminal state or RNG'):F.audit_route(self.x,wrong,self.policy,self.cp)

    def test_first_difference_must_be_policy_action_not_combat_or_terminal(self):
        original=F.E.read(self.refs[0]['path']);wrong=copy.deepcopy(original)
        battle=next(s for s in wrong['prefix'] if s['kind']=='battle');battle['actions']=[]
        with self.assertRaisesRegex(ValueError,'first policy divergence'):F.first_change(self.x,original,wrong)
        wrong=copy.deepcopy(original);wrong['hp']+=1
        with self.assertRaisesRegex(ValueError,'same decisions'):F.first_change(self.x,original,wrong)
        wrong=copy.deepcopy(original);next(s for s in wrong['prefix'] if s['kind']=='outside')['action']+=1
        self.assertEqual(F.first_change(self.x,original,wrong)['kind'],'noncombat')


if __name__=='__main__':unittest.main()
