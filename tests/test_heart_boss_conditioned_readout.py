import copy
import importlib.util
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('E139_STUDY'),'requires prepared existing fit source')
class BossConditioningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['E139_STUDY']);p=cls.root/'program/heart_existing_data_experiment.py'
        spec=importlib.util.spec_from_file_location('e139_test_E',p);cls.E=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.E)
        cls.L,cls.N,cls.V=cls.E.modules(cls.root);cls.plan=cls.E.read(cls.root/'protocol.json')
        cls.bundle=cls.E.read(cls.root/'fit-inputs.json.gz')
        cls.old=cls.L.torch.load(Path(cls.plan['control_study']).parent/'heart-e134-existing-data-representation-20260922-01/learning/candidate.pt',weights_only=True,map_location='cpu')
        cls.base=cls.L.H.load_scorer(cls.old);cls.extended=cls.N.extend_checkpoint(cls.old)
        cls.policy=cls.L.H.load_scorer(cls.extended);cls.trees=cls.bundle['trees'][:4]
        cls.config=cls.E.read(cls.root/'runtime/config.json')

    def states(self):
        for tree in self.trees:
            yield 'relic',tree['boss_root']
            for branch in tree['branches']:
                if branch['card_root'] is not None:yield 'card',self.bundle['states'][branch['card_root']]

    def restore(self,state):
        source=self.E.read(state['source_path'])
        gc=self.V.R.replay(state['seed'],source['prefix'][:state['prefix_index']],self.config)
        self.assertEqual(self.V.R.fingerprint(gc),state['fingerprint']);return gc

    def test_extension_preserves_all_original_features_and_zero_added_control(self):
        for stage,state in self.states():
            gc=self.restore(state);obs=self.V.A.obs_vec(gc);actions=list(self.V.R.sts.get_legal_game_actions(gc));_,desc,_=self.V.A.build_choices(gc)
            observation=self.L.torch.tensor([obs]*len(desc));descriptors=self.L.torch.tensor(desc)
            before=self.base.embed(observation,descriptors);after=self.policy.embed(observation,descriptors)
            self.assertTrue(self.L.torch.equal(before,after[:,:192]))
            self.assertEqual(self.base.choose(gc,obs,actions,desc),self.policy.choose(gc,obs,actions,desc))
            self.E.native_decision(self.N,self.V,self.policy,self.extended,gc,stage)

    def test_native_features_and_nonzero_added_weights_agree(self):
        artifact=copy.deepcopy(self.extended)
        artifact['card_state']['weight'][192:]=self.L.torch.linspace(-.4,.7,len(artifact['card_state']['weight'])-192)
        policy=self.L.H.load_scorer(artifact)
        for stage,state in self.states():self.E.native_decision(self.N,self.V,policy,artifact,self.restore(state),stage)

    def test_boss_condition_can_reverse_card_versus_skip_preference(self):
        torch=self.L.torch;A=self.V.A
        state=next(state for stage,state in self.states() if stage=='card')
        observation=torch.tensor([self.V.R.dense(state['observation'],A.OBS_DIM)]*len(state['candidates']))
        descriptors=torch.tensor([self.V.R.dense(state['descriptors'][i],A.DESC_DIM) for i in state['candidates']])
        artifact=self.N.artifact(self.old['base_checkpoint'],self.old['relic_support'],self.old['card_support'],{})
        policy=self.N.BossConditionedPolicy(artifact);ids=policy.boss_identities
        observation[:,[self.N.N.RELIC_OFFSET+i for i in ids]]=0.
        a=observation.clone();b=observation.clone();a[:,self.N.N.RELIC_OFFSET+ids[0]]=1.;b[:,self.N.N.RELIC_OFFSET+ids[1]]=1.
        with torch.no_grad():policy.card.weight[192]=3.;policy.card.weight[193]=-3.
        ea,eb=policy.embed(a,descriptors),policy.embed(b,descriptors)
        self.assertTrue(torch.equal(ea[:,:192],eb[:,:192]));self.assertFalse(torch.equal(ea[:,192:],eb[:,192:]))
        lookup=torch.tensor([[policy.card_positions[self.L.J.card_option(d)] for d in descriptors.tolist()]])
        baseline=torch.tensor([state['candidates'].index(state['chosen'])]);mask=torch.ones(lookup.shape,dtype=torch.bool)
        ra=policy.card(ea[None],lookup,baseline,mask)[0];rb=policy.card(eb[None],lookup,baseline,mask)[0]
        winner_a=int(ra.argmax());winner_b=int(rb.argmax())
        self.assertLess(self.L.J.card_option(descriptors[winner_a].tolist()),A.CARD_CAP)
        self.assertGreaterEqual(self.L.J.card_option(descriptors[winner_b].tolist()),A.CARD_CAP)

    def test_unknown_whole_offer_still_uses_parent(self):
        state=next(state for stage,state in self.states() if stage=='card');gc=self.restore(state)
        actions=list(self.V.R.sts.get_legal_game_actions(gc));_,desc,_=self.V.A.build_choices(gc);obs=self.V.A.obs_vec(gc)
        omitted=self.L.J.card_option(desc[state['chosen']])
        support=[i for i in self.old['card_support'] if i!=omitted]
        artifact=self.N.artifact(self.old['base_checkpoint'],self.old['relic_support'],support,{})
        policy=self.N.BossConditionedPolicy(artifact)
        with self.L.torch.no_grad():policy.card.weight.fill_(5.);policy.card.static_scores.copy_(self.L.torch.linspace(-50,50,len(support)))
        self.assertEqual(policy.choose(gc,obs,actions,desc),policy.base.choose(gc,obs,actions,desc))


if __name__=='__main__':unittest.main()
