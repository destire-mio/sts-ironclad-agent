import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_continuous_training as T


class ContinuousTrainingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.source=Path(os.environ['E143_STUDY'])
        cls.nodes=T.E.read(cls.source/'fit-nodes.json')[:4]
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'store'
        T.build_store(cls.source,cls.path,cls.nodes);cls.store=T.Store(cls.path)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_decomposed_menus_match_dense_features_outputs_and_gradients(self):
        rows=[];ids=[];at=0
        for n in self.nodes:
            d=T.E.read(self.source/'families'/f'{n["seed"]}.json.gz')
            for route in d['routes']:
                for j,row in enumerate(route['rows']):
                    if j==route['root_position'] or (j==0 and route['parent_control']):
                        rows.append(row);ids.append(at)
                    at+=1
        model=T.V.ContinuousValue(self.store.spec['width']);model.tail[-1].weight.data.fill_(.0125)
        other=copy.deepcopy(model);dense=[]
        for row in rows:
            for choice in range(len(row['descriptors'])):
                v=torch.zeros(self.store.spec['width'])
                for i,value in T.C.sparse_features(row,choice,self.store.spec):v[i]=value
                dense.append(v)
        expected=other(torch.stack(dense));actual,ptr,chosen=self.store.logits(model,ids,True)
        torch.testing.assert_close(actual,expected,rtol=2e-5,atol=2e-6)
        expected.square().sum().backward();actual.square().sum().backward()
        for a,b in zip(model.parameters(),other.parameters()):
            torch.testing.assert_close(a.grad,b.grad,rtol=3e-4,atol=2e-5)
        direct=self.store.logits(model,ids)[0]
        torch.testing.assert_close(direct,actual[torch.as_tensor(chosen)],rtol=2e-5,atol=2e-6)
        self.assertEqual(ptr[-1],len(dense))

    def test_temporal_targets_stop_at_route_boundaries_and_exclude_held_families(self):
        model=T.V.ContinuousValue(self.store.spec['width'])
        fit=self.store.families[:2];others=self.store.families[2:]
        for lam in (1.,.8):
            targets=T.targets_for(self.store,model,fit,lam)
            for f in fit:
                for r in f['routes']:
                    expected=np.asarray(T.V.lambda_returns([.1]*(r['end']-r['begin']),r['target'],lam))
                    np.testing.assert_allclose(targets[r['begin']:r['end']],expected,rtol=1e-5,atol=1e-6)
                    self.assertEqual(targets[r['end']-1],r['target'])
            for f in others:
                for r in f['routes']:self.assertTrue(np.isnan(targets[r['begin']:r['end']]).all())

    def test_recorded_action_loss_matches_independent_menu_cross_entropy_and_gradients(self):
        logits=torch.tensor([-.7,.4,1.2,-.4,.3,2.],requires_grad=True);other=logits.detach().clone().requires_grad_()
        ptr=np.asarray([0,2,3,6]);chosen=np.asarray([1,2,3]);target=torch.tensor([1.,0.,.25])
        loss,_,_=T.objective(logits,ptr,chosen,target,.05)
        ce=torch.stack([torch.logsumexp(other[a:b],0)-other[c] for a,b,c in zip(ptr[:-1],ptr[1:],chosen)]).mean()
        expected=torch.nn.functional.binary_cross_entropy_with_logits(other[chosen],target)+.05*ce
        torch.testing.assert_close(loss,expected);loss.backward();expected.backward()
        torch.testing.assert_close(logits.grad,other.grad)

    def test_sampling_keeps_fit_families_and_visits_all_available_stages(self):
        fit=self.store.families[:2];rng=np.random.default_rng(71)
        rows=T.sample_rows(fit,rng.random((60000,5)))
        allowed={i for f in fit for r in f['routes'] for i in range(r['begin'],r['end'])}
        self.assertTrue(set(rows)<=allowed)
        for f in fit:
            for r in f['routes']:
                self.assertIn(r['root'],rows)
                for act in r['acts']:self.assertTrue(set(act)&set(rows))
        again=T.sample_rows(fit,np.random.default_rng(71).random((60000,5)))
        np.testing.assert_array_equal(rows,again)

    def test_optimizer_learns_discriminating_actions_on_tiny_complete_menus(self):
        class Toy:
            rows=4;spec={'width':2}
            families=[dict(routes=[dict(begin=0,end=2,root=0,acts=[[1]],target=1),
                                   dict(begin=2,end=4,root=2,acts=[[3]],target=0)])]
            def logits(self,model,rows,all_menu=False):
                dense=[];chosen=[];ptr=[0]
                for r in rows:
                    good=torch.tensor([1.,0.]);bad=torch.tensor([0.,1.])
                    if all_menu:
                        dense.extend([good,bad]);chosen.append(ptr[-1]+int(r>=2));ptr.append(ptr[-1]+2)
                    else:dense.append(good if r<2 else bad)
                return model(torch.stack(dense)),np.asarray(ptr),np.asarray(chosen)
        toy=Toy();recipe=dict(T.RECIPE,iterations=2,steps_per_iteration=40,batch_size=16)
        model,history=T.fit_model(toy,toy.families,1.,91,recipe)
        with torch.no_grad():p=model(torch.eye(2)).sigmoid().tolist()
        self.assertGreater(p[0],.5);self.assertLess(p[1],.2);self.assertEqual(len(history),2)


if __name__=='__main__':unittest.main()
