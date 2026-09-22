import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('diagnosis',Path(__file__).resolve().parents[1]/'docs/experiments/e155-control-diagnosis.py')
D=importlib.util.module_from_spec(spec);spec.loader.exec_module(D)


class RecordedGraphTests(unittest.TestCase):
    def test_terminal_signal_crosses_long_unbranched_prefix(self):
        n=103
        # Two terminal alternatives at the last state; every earlier choice
        # has exactly one recorded successor and must retain its full value.
        states=list(range(n))+[n-1];done=[False]*(n-1)+[True,True]
        successors=list(range(1,n))+[n-1,n-1]
        result=D.solve_graph(n,states,successors,[0]*n+[1],done,[0]*n+[1],[0]*n)
        np.testing.assert_allclose(result[0],.7,atol=1e-12)
        np.testing.assert_array_equal(result[2],0)
        np.testing.assert_array_equal(result[3],1)
        self.assertEqual(result[4][0],103)

    def test_two_branches_merge_before_later_decision(self):
        # Both early actions meet at state1; the winner is chosen there, not
        # retroactively assigned as reward to the earlier two actions.
        v,q,parent,best,depth=D.solve_graph(2,[0,0,1,1],[1,1,0,0],[0,0,0,1],
            [False,False,True,True],[0,1,0,1],[0,0])
        np.testing.assert_allclose(q,[.7,.7,0,1],atol=1e-12)
        np.testing.assert_allclose(v,[.7,.7],atol=1e-12)
        np.testing.assert_array_equal(parent,[0,0]);np.testing.assert_array_equal(depth,[2,1])

    def test_cycle_is_not_treated_as_zero_return(self):
        with self.assertRaisesRegex(AssertionError,'cycle'):
            D.solve_graph(2,[0,1],[1,0],[0,0],[False,False],[0,0],[0,0])


if __name__=='__main__':unittest.main()
