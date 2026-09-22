"""E135 contracts on completed fit data, without a sampling/holdout entry."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('E135_STUDY'), 'requires prepared E135 fit data')
class StaticContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['E135_STUDY'])
        path=cls.root/'program/heart_static_context_experiment.py'
        spec=importlib.util.spec_from_file_location('e135_test',path)
        cls.F=importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.F)
        cls.E=cls.F.E; cls.L,cls.N,cls.V=cls.E.modules(cls.root)
        cls.bundle=cls.E.read(cls.root/'fit-inputs.json.gz'); cls.roles=cls.E.read(cls.root/'fit-roles.json')
        cls.plan=cls.E.read(cls.root/'protocol.json')
        cls.old=cls.L.torch.load(cls.plan['control_checkpoint'],weights_only=True,map_location='cpu')
        cls.support=(cls.old['relic_support'],cls.old['card_support'])

    def test_roles_reject_external_or_extra_state(self):
        self.F.admit_fit(self.bundle,self.roles)
        bundle=copy.deepcopy(self.bundle); bundle['references'][0]['split']='label_holdout'
        with self.assertRaisesRegex(ValueError,'non-fit'): self.F.admit_fit(bundle,self.roles)
        bundle=copy.deepcopy(self.bundle); bundle['states']['extra']=next(iter(bundle['states'].values()))
        with self.assertRaisesRegex(ValueError,'unassigned'): self.F.admit_fit(bundle,self.roles)

    def test_static_learns_bias_without_context_or_parent_updates(self):
        artifact,policy=self.F.policy_for(self.N,self.old['base_checkpoint'],self.support,'static',{})
        train,_=self.F.partition(self.L,self.bundle,set(self.roles[:48]),self.support)
        for s in ('card','relic'):
            train[s]['readout_embeddings']=policy.embeddings(train[s]['rows'],train[s]['mask'].shape[-1])
        params=[p for p in policy.parameters() if p.requires_grad]
        self.assertEqual(sum(p.numel() for p in params),sum(map(len,self.support)))
        optimizer=self.L.torch.optim.Adam(params,lr=.03)
        loss,_=self.L.objective(policy,train,.001); loss.backward()
        self.assertTrue(any(bool(p.grad.count_nonzero()) for p in params))
        self.assertTrue(all(p.grad is None for p in policy.base.parameters()))
        optimizer.step()
        for s in ('card','relic'):
            head=getattr(policy,s); self.assertIsNone(head.weight.grad)
            self.assertFalse(bool(head.weight.count_nonzero()))
            group=train[s]
            first=head(group['readout_embeddings'],group['positions'],group['baseline'],group['mask'])
            changed=head(group['readout_embeddings']*17+3,group['positions'],group['baseline'],group['mask'])
            self.assertTrue(self.L.torch.equal(first,changed))
        artifact.update(**self.L.head_states(policy))
        loaded=self.L.H.load_scorer(artifact)
        self.assertEqual(self.L.L.deterministic_outcomes(policy,train),self.L.L.deterministic_outcomes(loaded,train))

    def test_native_bias_override_is_readonly_and_respects_parent_scope(self):
        artifact,policy=self.F.policy_for(self.N,self.old['base_checkpoint'],self.support,'static',{})
        for stage in ('relic','card'):
            with self.L.torch.no_grad(): getattr(policy,stage).static_scores.copy_(
                self.L.torch.linspace(-2,2,len(artifact[stage+'_support'])))
        artifact.update(**self.L.head_states(policy)); loaded=self.L.H.load_scorer(artifact)
        config=self.E.read(self.root/'runtime/config.json')
        for tree in self.bundle['trees'][:4]:
            states=[('relic',tree['boss_root'])]+[('card',self.bundle['states'][b['card_root']])
                for b in tree['branches'] if b['card_root'] is not None]
            for stage,state in states:
                source=self.E.read(state['source_path'])
                gc=self.V.R.replay(state['seed'],source['prefix'][:state['prefix_index']],config)
                self.assertEqual(self.V.R.fingerprint(gc),state['fingerprint'])
                self.E.native_decision(self.N,self.V,loaded,artifact,gc,stage)

    def test_closed_study_rejects_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'source-closed.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'closed'): self.F.run(root)
            self.assertFalse((root/'result').exists())


if __name__=='__main__': unittest.main()
