import copy
import math
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_continuous_development as D


def counts(gain,loss):
    discordant=gain+loss
    p=min(1.,2*sum(math.comb(discordant,k) for k in range(min(gain,loss)+1))/2**discordant) if discordant else 1.
    return dict(assigned=128,baseline_wins=20,candidate_wins=20+gain-loss,net_gain=gain-loss,
        paired=dict(both_win=20-loss,baseline_only=loss,candidate_only=gain,both_fail=108-gain),exact_p=p)


def review(mc,td):
    arms={}
    for name,c in zip(D.T.ARMS,[mc,td]):
        arms[name]=dict(counts=c,gate_passed=c['net_gain']>=8 and c['exact_p']<.025)
    return dict(status='complete_not_adopted',zero_faults=True,natural_policy_evaluation_games=256,arms=arms)


class ContinuousDevelopmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=Path(os.environ['E144_STUDY']);cls.data=Path(D.E.read(cls.source/'protocol.json')['source'])
        cls.groups=D.E.read(Path(os.environ['E145_GROUPS']))
        cls.fit=D.E.read(cls.data/'fit-roles.json');cls.dev=cls.groups['development']

    def test_whole_run_selection_rejects_failed_partial_and_faulted_screens(self):
        bad=review(counts(4,2),counts(5,2))
        with self.assertRaisesRegex(ValueError,'neither'):D.selected_arm(bad)
        good=review(counts(12,0),counts(11,1))
        for field,value in [('status','running'),('zero_faults',False),('natural_policy_evaluation_games',128)]:
            changed=copy.deepcopy(good);changed[field]=value
            with self.assertRaisesRegex(ValueError,'incomplete'):D.selected_arm(changed)
        changed=copy.deepcopy(good);changed['arms']['monte_carlo']['counts']['assigned']=127
        with self.assertRaisesRegex(ValueError,'denominator'):D.selected_arm(changed)

    def test_selection_uses_net_wins_then_parent_losses_then_monte_carlo(self):
        self.assertEqual(D.selected_arm(review(counts(12,0),counts(14,1))),'temporal')
        self.assertEqual(D.selected_arm(review(counts(13,1),counts(12,0))),'temporal')
        self.assertEqual(D.selected_arm(review(counts(12,0),counts(12,0))),'monte_carlo')
        changed=review(counts(12,0),counts(5,2));changed['arms']['temporal']['gate_passed']=True
        with self.assertRaisesRegex(ValueError,'threshold'):D.selected_arm(changed)

    def test_exact_all_fit_and_reserved_roles_and_overlap_rejection(self):
        D.validate_roles(self.fit,self.dev,self.groups)
        with self.assertRaisesRegex(ValueError,'all-fit'):D.validate_roles(self.fit[:-1],self.dev,self.groups)
        bad=copy.deepcopy(self.groups);bad['development'][0]=bad['small_fit'][0]
        with self.assertRaisesRegex(ValueError,'overlaps'):D.validate_roles(self.fit,bad['development'],bad)
        with self.assertRaisesRegex(ValueError,'reserved'):D.validate_roles(self.fit,self.dev[::-1],self.groups)

    def test_final_checkpoint_cannot_be_fold_model_or_see_development_seed(self):
        cp=dict(model_type='continuous_fixed_parent_value',provenance=dict(scope='full_fit_natural_development',
            fold=None,arm='monte_carlo',fit_families=self.fit,optimizer_updates=20000,protocol_sha256='bound'))
        D.guard_checkpoint(cp,self.dev[0],self.fit,'monte_carlo','bound')
        for key,value in [('fold',0),('arm','temporal'),('scope','single_card')]:
            bad=copy.deepcopy(cp);bad['provenance'][key]=value
            with self.assertRaisesRegex(ValueError,'wrong full-fit'):D.guard_checkpoint(bad,self.dev[0],self.fit,'monte_carlo','bound')
        with self.assertRaisesRegex(ValueError,'entered fitting'):D.guard_checkpoint(cp,self.fit[0],self.fit,'monte_carlo','bound')
        bad=copy.deepcopy(cp);bad['provenance']['fit_families']=self.fit[:-1]
        with self.assertRaisesRegex(ValueError,'entered fitting'):D.guard_checkpoint(bad,self.dev[0],self.fit,'monte_carlo','bound')
        with self.assertRaisesRegex(ValueError,'protocol'):D.guard_checkpoint(cp,self.dev[0],self.fit,'monte_carlo','changed')


if __name__=='__main__':unittest.main()
