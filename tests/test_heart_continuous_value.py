import itertools
import os
from pathlib import Path
import sys
import unittest


@unittest.skipUnless(os.environ.get('E143_STUDY'),'requires frozen complete route source')
class ContinuousValueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(os.environ['E143_STUDY']);sys.path.insert(0,str(root/'program'))
        import heart_continuous_value as V
        cls.V=V;cls.C=V.C;cls.t=V.torch;cls.plan,cls.nodes,_=cls.C.registered(root)
        cls.x=cls.C.D.runtime(cls.plan['runtime']);cls.spec=cls.C.spec_for(cls.x)
        cls.base=cls.t.load(Path(cls.plan['runtime'])/'model.pt',weights_only=True,map_location='cpu')

    def test_lambda_backward_matches_forward_n_step_mixture_and_terminal(self):
        q=[.1,.2,.7,.4];lam=.8
        expected=[]
        for at in range(len(q)):
            length=len(q)-at
            expected.append(sum((1-lam)*lam**(n-1)*q[at+n] for n in range(1,length))+lam**(length-1))
        actual=self.V.lambda_returns(q,1,lam)
        for a,b in zip(actual,expected):self.assertAlmostEqual(a,b)
        self.assertEqual(self.V.lambda_returns(q,1,1),[1.]*4)
        self.assertEqual(self.V.lambda_returns(q,0,1),[0.]*4)
        self.assertEqual(self.V.lambda_returns(q,0,0),[.2,.7,.4,0.])

    def test_sparse_and_dense_predictions_and_parameter_gradients_match(self):
        t=self.t;t.manual_seed(4);a=self.V.ContinuousValue(6);b=self.V.ContinuousValue(6)
        a.tail[-1].weight.data.fill_(.1);b.load_state_dict(a.state_dict())
        dense=t.tensor([[0.,.1,0.,.4,0.,1.],[1.,0.,0.,.4,.3,0.]])
        la=a(dense);lb=b(dense.to_sparse())
        self.assertTrue(t.allclose(la,lb,atol=1e-6,rtol=1e-6))
        la.square().mean().backward();lb.square().mean().backward()
        for p,q in zip(a.parameters(),b.parameters()):self.assertTrue(t.allclose(p.grad,q.grad,atol=1e-6,rtol=1e-5))

    def test_constant_values_recover_parent_over_complete_natural_routes(self):
        cp=dict(model_type='continuous_fixed_parent_value',feature_spec=self.spec,support=[],
                base_checkpoint=self.base,value_state=self.V.ContinuousValue(self.spec['width']).state_dict())
        policy=self.V.ContinuousPolicy(cp,self.x)
        for node in self.nodes[:4]:
            raw=self.C.E.read(node['state']['source_path'])
            gc=self.x.R.sts.GameContext(self.x.R.sts.CharacterClass.IRONCLAD,node['seed'],20)
            for step in raw['prefix']:
                self.x.R.clock_input(gc,self.x.config)
                if step['kind']=='outside':
                    actions=list(self.x.R.sts.get_legal_game_actions(gc));_,desc,_=self.x.A.build_choices(gc)
                    row=dict(descriptors=[self.x.R.sparse(d) for d in desc])
                    policy.support={self.C.support_key(d,self.spec) for d in row['descriptors']}
                    before=self.x.R.fingerprint(gc);choice=policy.choose(gc,self.x.A.obs_vec(gc),actions,desc)
                    self.assertEqual(int(actions[choice].bits),step['action'])
                    self.assertEqual(before,self.x.R.fingerprint(gc))
                self.x.R.replay_step(gc,step,self.x.config)
            self.x.R.clock_input(gc,self.x.config);self.x.P.verify_terminal(gc,raw)

    def test_support_masks_only_unknown_alternatives_and_keeps_parent(self):
        row=dict(descriptors=[[(0,1.)],[(1,1.)],[(2,1.)]])
        spec=dict(support_columns=[0,1,2]);allowed={self.C.support_key(row['descriptors'][1],spec)}
        self.assertEqual(self.V.select(row,[.1,.4,.9],0,allowed,spec),1)
        self.assertEqual(self.V.select(row,[.1,.4,.9],0,set(),spec),0)
        self.assertEqual(self.V.select(row,[.4,.4,.9],0,allowed,spec),0)


if __name__=='__main__':unittest.main()
