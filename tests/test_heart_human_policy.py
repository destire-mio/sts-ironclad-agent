from pathlib import Path
import sys
import unittest
import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_human_policy as P
import heart_human_admission as A


class HumanPolicyContract(unittest.TestCase):
    def test_candidates_are_permutation_equivariant(self):
        net=P.Student(8,True)
        with torch.no_grad():net.value.weight.copy_(torch.arange(108).reshape(9,12)/100)
        state=torch.tensor(P.context({2:4,5:1},1,6,8,True)[None])
        options=torch.tensor([[2,5,8]]);upgrades=torch.tensor([[0.,1.,0.]],dtype=torch.float64)
        a=net(state,options,upgrades);b=net(state,options[:,[2,0,1]],upgrades[:,[2,0,1]])
        torch.testing.assert_close(a[:,[2,0,1]],b)

    def test_label_and_identity_not_in_input(self):
        row=dict(deck={'A':2},offered=['A','B+1'],picked='A',act=1,floor=5,family=42,role='fit')
        other={**row,'picked':'SKIP','family':9,'role':'held'}
        a=P.encode(row,{'A':1,'B':2},8,True);b=P.encode(other,{'A':1,'B':2},8,True)
        np.testing.assert_array_equal(a['state'],b['state']);self.assertEqual(a['options'],b['options'])
        self.assertNotEqual(a['target'],b['target'])

    def test_earlier_event_hazard_censors_future_choices(self):
        run=dict(boss_relics=[dict(picked='Cursed Key')],event_choices=[dict(floor=13,relics_obtained=['Omamori'])])
        self.assertEqual(A.uncertainty(run),(13,'relic:Omamori'))
        self.assertEqual(A.uncertainty(dict(damage_taken=[dict(floor=40,enemies='Writhing Mass')])),(40,'encounter:Writhing Mass'))


if __name__=='__main__':unittest.main()
