import copy
from itertools import product
import os
from pathlib import Path
import sys
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('E141_STUDY'), 'requires frozen value-study runtime')
class TrajectoryValueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['E141_STUDY'])
        sys.path.insert(0, str(cls.root/'program'))
        import heart_trajectory_value_training as F
        cls.F = F; cls.D = F.D; cls.V = F.V; cls.E = F.E; cls.t = F.torch
        cls.plan = F.registered(cls.root, require_data=False)
        cls.x = cls.D.runtime(cls.plan['runtime']); cls.spec = cls.D.feature_spec(cls.x)
        cls.nodes = cls.E.read(Path(cls.plan['source'])/'fit-nodes.json')
        cls.base = cls.t.load(Path(cls.plan['runtime'])/'model.pt', weights_only=True, map_location='cpu')
        cls.support = sorted({cls.x.J.card_option(cls.x.R.dense(n['state']['descriptors'][c],cls.x.A.DESC_DIM))
            for n in cls.nodes for c in n['state']['candidates']})

    def artifact(self):
        model = self.V.ValueNetwork(self.spec['width'])
        for p in model.parameters(): p.data.zero_()
        return dict(model_type='first_card_trajectory_value', feature_spec=self.spec,
                    card_support=self.support, value_state=model.state_dict(), base_checkpoint=self.base)

    def test_bce_target_gradient_and_trainable_representation(self):
        t = self.t; logits = t.tensor([.2,-.4],requires_grad=True,dtype=t.float64)
        target = t.tensor([1.,0.],dtype=t.float64)
        t.nn.functional.binary_cross_entropy_with_logits(logits,target).backward()
        self.assertTrue(t.allclose(logits.grad,(logits.detach().sigmoid()-target)/2,atol=1e-12,rtol=0))
        t.manual_seed(17); model = self.V.ValueNetwork(4); original = model.layers[0].weight.detach().clone()
        optimizer = t.optim.AdamW(model.parameters(),lr=.001)
        t.nn.functional.binary_cross_entropy_with_logits(model(t.eye(4)),t.tensor([1.,0.,1.,0.])).backward()
        optimizer.step()
        self.assertFalse(t.equal(original,model.layers[0].weight))

    def test_hierarchical_sampling_keeps_equal_families_and_branches(self):
        families = [dict(branches=[dict(root=10,later=[[11],[12]]),dict(root=20,later=[[21,22]])]),
                    dict(branches=[dict(root=30,later=[]),dict(root=40,later=[[41,42]])])]
        grid = list(product((.25,.75),repeat=5))
        control = self.F.sample_rows(families,grid,'root_only')
        dense = self.F.sample_rows(families,grid,'root_plus_later')
        self.assertEqual({r:control.count(r) for r in set(control)},{10:8,20:8,30:8,40:8})
        self.assertEqual({r:dense.count(r) for r in (10,20,30,40)},{10:4,20:4,30:8,40:4})
        self.assertEqual(sum(r<30 for r in dense),16)

    def test_constant_values_preserve_parent_on_full_existing_routes(self):
        policy = self.V.ValuePolicy(self.artifact(), self.x)
        for node in self.nodes[:4]:
            source = self.E.read(node['state']['source_path'])
            gc = self.x.R.sts.GameContext(self.x.R.sts.CharacterClass.IRONCLAD,node['seed'],20)
            for step in source['prefix']:
                self.x.R.clock_input(gc,self.x.config)
                if step['kind'] == 'outside':
                    actions = list(self.x.R.sts.get_legal_game_actions(gc)); _,desc,_ = self.x.A.build_choices(gc)
                    before = self.x.R.fingerprint(gc)
                    chosen = policy.choose(gc,self.x.A.obs_vec(gc),actions,desc)
                    self.assertEqual(int(actions[chosen].bits),step['action'])
                    self.assertEqual(before,self.x.R.fingerprint(gc))
                self.x.R.replay_step(gc,step,self.x.config)
            self.x.R.clock_input(gc,self.x.config);self.x.P.verify_terminal(gc,source)

    def test_nonzero_value_native_decoder_scores_and_unknown_menu(self):
        node = self.nodes[0]; state = node['state']; cp = self.artifact(); A = self.x.A
        alternative = next(i for i in state['candidates'] if i != state['chosen'] and
                           self.x.J.card_option(self.x.R.dense(state['descriptors'][i],A.DESC_DIM)) < A.CARD_CAP)
        identity = self.x.J.card_option(self.x.R.dense(state['descriptors'][alternative],A.DESC_DIM))
        column = len(self.spec['observations'])+self.spec['descriptors'].index(A.OFF_CARD+identity)
        cp['value_state']['layers.0.weight'][0,column]=1.
        cp['value_state']['layers.2.weight'][0,0]=1.
        cp['value_state']['layers.4.weight'][0,0]=1.
        expected = dict(seed=node['seed'],candidate=alternative,target=next(l['target'] for l in node['leaves'] if l['candidate']==alternative))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'model.pt';self.t.save(cp,path)
            job=dict(seed=node['seed'],node=node,expected=expected,checkpoint=str(path),checkpoint_sha256=self.E.sha(path),
                     runtime=self.plan['runtime'],output=str(Path(folder)/'result.json'))
            self.F.native_worker(job,self.x.config);self.assertEqual(self.E.read(job['output'])['status'],'complete')
            wrong=copy.deepcopy(job);wrong['expected']['target']^=1;wrong['output']=str(Path(folder)/'wrong.json')
            self.F.native_worker(wrong,self.x.config);self.assertEqual(self.E.read(wrong['output'])['status'],'verification_error')
        source=self.E.read(state['source_path']);gc=self.x.R.replay(node['seed'],source['prefix'][:state['prefix_index']],self.x.config)
        acts=list(self.x.R.sts.get_legal_game_actions(gc));_,desc,_=A.build_choices(gc)
        cp['card_support']=[i for i in self.support if i != identity]
        policy=self.V.ValuePolicy(cp,self.x)
        self.assertEqual(policy.choose(gc,A.obs_vec(gc),acts,desc),state['chosen'])

    def test_nonzero_values_leave_all_out_of_scope_decisions_on_parent(self):
        cp=self.artifact();self.t.manual_seed(19)
        cp['value_state']=self.V.ValueNetwork(self.spec['width']).state_dict()
        policy=self.V.ValuePolicy(cp,self.x);node=self.nodes[0]
        source=self.E.read(node['state']['source_path'])
        gc=self.x.R.sts.GameContext(self.x.R.sts.CharacterClass.IRONCLAD,node['seed'],20);checked=0
        for step in source['prefix']:
            self.x.R.clock_input(gc,self.x.config)
            if step['kind']=='outside':
                acts=list(self.x.R.sts.get_legal_game_actions(gc));_,desc,_=self.x.A.build_choices(gc);obs=self.x.A.obs_vec(gc)
                parent=policy.base.choose(gc,obs,acts,desc)
                if not self.E.early_card_eligible(self.x,gc,desc,parent):
                    self.assertEqual(policy.choose(gc,obs,acts,desc),parent);checked+=1
            self.x.R.replay_step(gc,step,self.x.config)
        self.assertGreater(checked,20)

    def test_original_family_split_and_missing_data_gate(self):
        import heart_relic_card_readout_training as old
        self.assertTrue(all(self.F.fold(n['seed'])==old.fold(n['seed'],3) for n in self.nodes))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=dict(self.plan,source=str(root/'missing'))
            self.E.write(root/'protocol.json',plan)
            self.E.write(root/'registration.json',dict(runner_sha256=self.E.sha(self.F.__file__),
                hashes={str(root/'protocol.json'):self.E.sha(root/'protocol.json')}))
            with self.assertRaises(FileNotFoundError):self.F.train(root)
            self.assertFalse((root/'learning').exists())


if __name__=='__main__':unittest.main()
