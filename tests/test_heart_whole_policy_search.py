"""Paired whole-policy credit, bounded updates, and deterministic deployment."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_whole_policy_search as L


class WholePolicySearchTests(unittest.TestCase):
    def test_two_decision_terminal_reward_updates_the_whole_policy(self):
        directions=np.array([[1,1],[1,-1],[-1,1],[-1,-1]],dtype=float)
        theta=np.zeros(2)
        # Both choices use this same deterministic policy during training and
        # deployment. Only the joint positive choices reach the toy terminal.
        reward=lambda p:float(p[0]>0 and p[1]>0)
        result,mass=L.paired_update(theta,directions,[reward(v) for v in directions],
                                   [reward(-v) for v in directions],1.)
        np.testing.assert_array_equal(result,[1,1]);self.assertEqual(mass,2.)
        self.assertEqual(reward(theta),0.);self.assertEqual(reward(result),1.)
        np.testing.assert_array_equal(theta,[0,0])

    def test_equal_paired_returns_have_no_update(self):
        initial=np.array([.2,-.1]);directions=np.array([[3.,4.],[-4.,3.]])
        result,mass=L.paired_update(initial,directions,[.5,1.],[.5,1.],2.)
        np.testing.assert_array_equal(result,initial);self.assertEqual(mass,0.)
        self.assertIsNot(result,initial)

    def test_swapping_both_pair_labels_and_directions_preserves_update(self):
        initial=np.array([.2,-.1]);directions=np.array([[3.,4.],[-4.,3.]])
        a,_=L.paired_update(initial,directions,[.75,.5],[.25,.25],.5)
        b,_=L.paired_update(initial,-directions,[.25,.25],[.75,.5],.5)
        np.testing.assert_allclose(a,b)
        expected=initial+.5*((.5*directions[0]+.25*directions[1])/.75)
        np.testing.assert_allclose(a,expected)

    def test_common_family_reward_offset_cancels(self):
        directions=np.eye(2);a,_=L.paired_update(np.zeros(2),directions,[.4,.2],[.2,.4],1.)
        b,_=L.paired_update(np.zeros(2),directions,[.7,.4],[.5,.6],1.)
        np.testing.assert_allclose(a,b)

    def test_invalid_rewards_and_shapes_are_rejected(self):
        for positive in ([float('nan'),0.],[2.,0.],[-1.,0.]):
            with self.assertRaises(ValueError):L.paired_update(np.zeros(2),np.eye(2),positive,[0.,0.],1.)
        with self.assertRaises(ValueError):L.paired_update(np.zeros(2),np.eye(3),[0.,0.,0.],[1.,1.,1.],1.)

    def test_ties_and_invalid_scores(self):
        self.assertEqual(L.select([1.,1.+1e-10,0.],0),0)
        self.assertEqual(L.select([2.,2.,1.],2),0)
        self.assertEqual(L.select([-np.inf,2.,1.],2),1)
        with self.assertRaises(ValueError):L.select([np.nan,1.],1)


if __name__=='__main__':unittest.main()
