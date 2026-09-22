import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('E137_STUDY'),'requires prepared first-card source/runtime')
class FirstCardTrainingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['E137_STUDY']); path=cls.root/'program/heart_first_card_training.py'
        spec=importlib.util.spec_from_file_location('e137_test',path)
        cls.F=importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.F); cls.E=cls.F.E
        cls.plan=cls.E.read(cls.root/'protocol.json'); cls.x,cls.L,cls.C=cls.F.modules(cls.plan['runtime'])
        cls.nodes=cls.E.read(cls.root/'fit-nodes.json'); cls.refs=cls.E.read(cls.root/'fit-references.json')
        cls.seeds={r['seed'] for r in cls.refs[:4]}
        cls.data,cls.support=cls.F.pack(cls.L,cls.nodes,cls.refs,cls.seeds,'fit')
        base=cls.x.H.torch.load(Path(cls.plan['runtime'])/'model.pt',weights_only=True,map_location='cpu')
        cls.artifact=cls.L.artifact_for(base,[cls.x.A.RELIC_CAP],cls.support,{},card=True,relic=False)

    def test_exact_terminal_expectation_and_gradient_match_enumeration(self):
        t=self.L.torch
        logits=t.tensor([[.3,-.4],[.1,.6]],requires_grad=True,dtype=t.float64)
        targets=t.tensor([[1.,0.],[0.,1.]],dtype=t.float64)
        value=self.F.mean_return(logits,targets)
        p=logits.detach().softmax(-1); expected=(p*targets).sum(-1).mean()
        self.assertAlmostEqual(float(value.detach()),float(expected),places=12)
        value.backward()
        derivative=p*(targets-(p*targets).sum(-1,keepdim=True))/2
        self.assertTrue(t.allclose(logits.grad,derivative,atol=1e-12,rtol=0))

    def test_zero_head_matches_parent_on_four_complete_existing_routes(self):
        policy=self.L.EarlyCardPolicy(self.artifact)
        self.assertFalse(policy.change_relic)
        for node in self.nodes[:4]:
            source=self.E.read(node['state']['source_path'])
            gc=self.x.R.sts.GameContext(self.x.R.sts.CharacterClass.IRONCLAD,node['seed'],20)
            for step in source['prefix']:
                self.x.R.clock_input(gc,self.x.config)
                if step['kind']=='outside':
                    actions=list(self.x.R.sts.get_legal_game_actions(gc));_,desc,_=self.x.A.build_choices(gc)
                    choice=policy.choose(gc,self.x.A.obs_vec(gc),actions,desc)
                    self.assertEqual(int(actions[choice].bits),step['action'])
                self.x.R.replay_step(gc,step,self.x.config)
            self.x.R.clock_input(gc,self.x.config);self.x.P.verify_terminal(gc,source)

    def test_nonzero_head_native_choice_and_wrong_target_rejection(self):
        policy=self.L.EarlyCardPolicy(self.artifact)
        state=self.data['nodes'][0]['state']; alternative=next(c for c in state['candidates'] if c!=state['chosen'])
        identity=self.L.J.card_option(self.x.R.dense(state['descriptors'][alternative],self.x.A.DESC_DIM))
        with self.L.torch.no_grad(): policy.card.static_scores[self.support.index(identity)]=3.
        artifact=self.L.checkpoint(policy,self.artifact,0); expected=self.F.choices(policy,self.data)
        self.assertEqual(expected[0]['candidate'],alternative)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'candidate.pt';self.L.torch.save(artifact,path)
            for node,row in zip(self.data['nodes'],expected):
                job=dict(seed=node['seed'],runtime=self.plan['runtime'],node=node,expected=row,
                         checkpoint=str(path),checkpoint_sha256=self.E.sha(path),output=str(root/f'{node["seed"]}.json'))
                self.F.native_worker(job,self.x.config);actual=self.E.read(job['output'])
                self.assertEqual(actual['status'],'complete',actual)
            wrong=copy.deepcopy(job);wrong['expected']['target']^=1;wrong['output']=str(root/'wrong.json')
            self.F.native_worker(wrong,self.x.config)
            self.assertEqual(self.E.read(wrong['output'])['status'],'verification_error')

    def test_nonzero_card_head_preserves_other_decisions_and_unknown_menu(self):
        policy=self.L.EarlyCardPolicy(self.artifact)
        with self.L.torch.no_grad(): policy.card.static_scores.copy_(self.L.torch.linspace(-50,50,len(self.support)))
        node=self.nodes[0];source=self.E.read(node['state']['source_path'])
        gc=self.x.R.sts.GameContext(self.x.R.sts.CharacterClass.IRONCLAD,node['seed'],20)
        checked=0
        for step in source['prefix']:
            self.x.R.clock_input(gc,self.x.config)
            if step['kind']=='outside':
                actions=list(self.x.R.sts.get_legal_game_actions(gc));_,desc,_=self.x.A.build_choices(gc);obs=self.x.A.obs_vec(gc)
                baseline=policy.base.choose(gc,obs,actions,desc)
                if not self.L.card_eligible(gc,desc,baseline):
                    self.assertEqual(policy.choose(gc,obs,actions,desc),baseline);checked+=1
            self.x.R.replay_step(gc,step,self.x.config)
        self.assertGreater(checked,20)
        state=node['state'];gc=self.x.R.replay(node['seed'],source['prefix'][:state['prefix_index']],self.x.config)
        actions=list(self.x.R.sts.get_legal_game_actions(gc));_,desc,_=self.x.A.build_choices(gc);obs=self.x.A.obs_vec(gc)
        omitted=self.L.J.card_option(desc[state['chosen']]);artifact=copy.deepcopy(self.artifact)
        artifact['card_support']=[i for i in self.support if i!=omitted]
        policy=self.L.EarlyCardPolicy(artifact)
        with self.L.torch.no_grad(): policy.card.static_scores.copy_(self.L.torch.linspace(-50,50,len(artifact['card_support'])))
        self.assertEqual(policy.choose(gc,obs,actions,desc),state['chosen'])

    def test_wrong_roles_missing_actions_and_cross_family_state_reject(self):
        refs=copy.deepcopy(self.refs);refs[0]['split']='label_holdout'
        with self.assertRaisesRegex(ValueError,'role'):self.F.pack(self.L,self.nodes,refs,self.seeds,'fit')
        nodes=copy.deepcopy(self.nodes);nodes[0]['leaves'].pop()
        with self.assertRaisesRegex(ValueError,'incomplete'):self.F.pack(self.L,nodes,self.refs,self.seeds,'fit')
        nodes=copy.deepcopy(self.nodes);nodes[0]['state']['seed']+=1
        with self.assertRaisesRegex(ValueError,'family'):self.F.pack(self.L,nodes,self.refs,self.seeds,'fit')

    def test_missing_source_audit_rejects_before_optimizer_or_learning_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=dict(self.plan,source=str(root/'missing-source'))
            self.E.write(root/'protocol.json',plan)
            self.E.write(root/'registration.json',dict(runner_sha256=self.E.sha(self.F.__file__),
                hashes={str(root/'protocol.json'):self.E.sha(root/'protocol.json')}))
            with self.assertRaises(FileNotFoundError):self.F.train(root)
            self.assertFalse((root/'learning').exists())


if __name__=='__main__':unittest.main()
