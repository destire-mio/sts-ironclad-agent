from pathlib import Path
import sys
import math
import unittest
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_adaptive_rollouts as A


class AdaptiveRolloutContract(unittest.TestCase):
    def test_process_counter_is_excluded_but_battle_state_is_not(self):
        a='hp: 17, loopCount: 6, sum: 10992, seed: 42 rng: 98'
        b='hp: 17, loopCount: 6, sum: 11015, seed: 42 rng: 98'
        self.assertEqual(A.state_repr(a),A.state_repr(b))
        for changed in (b.replace('hp: 17','hp: 16'),b.replace('rng: 98','rng: 99'),b.replace('loopCount: 6','loopCount: 7')):
            self.assertNotEqual(A.state_repr(a),A.state_repr(changed))
        with self.assertRaises(ValueError):A.state_repr('unknown battle layout')

    def test_empty_potion_slots_have_no_resource_value(self):
        sts=SimpleNamespace(Outcome=SimpleNamespace(UNDECIDED=0,PLAYER_VICTORY=1,PLAYER_ESCAPE=3))
        battle=SimpleNamespace(outcome=1,player=SimpleNamespace(cur_hp=5),turn=2,potions=[0,1])
        self.assertEqual(A.score(sts,battle),(1.,5.,0.,-2.))
        battle.potions=[1,3]
        self.assertEqual(A.score(sts,battle),(1.,5.,1.,-2.))

    def test_full_sequence_gradient_matches_finite_difference(self):
        frames=[((1,2,3),(.1,-.5,0.),1),((2,4),(.2,-.7),0)]
        policy={1:.2,2:-.1,3:.4,4:.6}; updated=A.adapt(policy,frames)
        def likelihood(p):return sum(math.log(A.probabilities(p,c,b)[i]) for c,b,i in frames)
        for code in policy:
            plus=dict(policy);minus=dict(policy);plus[code]+=1e-6;minus[code]-=1e-6
            gradient=(likelihood(plus)-likelihood(minus))/2e-6
            self.assertAlmostEqual(updated[code]-policy[code],gradient,places=8)
        self.assertEqual(policy,{1:.2,2:-.1,3:.4,4:.6})

    def test_menu_permutation_and_logit_translation(self):
        p={1:2.,2:-3.,3:5.};a=A.probabilities(p,(1,2,3),(0.,-.4,0.))
        b=A.probabilities({k:v+1000 for k,v in p.items()},(3,1,2),(0.,0.,-.4))
        for old,new in zip((a[2],a[0],a[1]),b):self.assertAlmostEqual(old,new,places=12)

    def test_adaptation_promotes_recorded_sequence(self):
        frames=[((1,2),(0.,0.),0),((3,4,5),(-2.3,0.,0.),2)]
        p={};before=math.prod(A.probabilities(p,c,b)[i] for c,b,i in frames)
        for _ in range(3):p=A.adapt(p,frames)
        after=math.prod(A.probabilities(p,c,b)[i] for c,b,i in frames)
        self.assertGreater(after,before)


if __name__=='__main__':unittest.main()
