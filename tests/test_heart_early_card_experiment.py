"""Actual-state verification and fail-before-fit behavior for E133."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('early_experiment',
    Path(__file__).resolve().parents[1]/'agent/heart_early_card_experiment.py')
P=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(P)


class IncompleteDataTest(unittest.TestCase):
    def test_missing_data_completion_rejects_before_fit_or_execution_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            study=Path(directory)
            P.write(study/'learning-registration.json',{'runner_sha256':P.sha(P.__file__),
                'hashes':{str(P.__file__):P.sha(P.__file__)}})
            with self.assertRaises(FileNotFoundError) as error:P.run(study)
            self.assertIn('data-execution-completion.json',str(error.exception))
            self.assertFalse((study/'learning').exists())
            self.assertFalse((study/'training-execution').exists())

    def test_missing_or_duplicate_data_stage_is_rejected(self):
        for stages in ([],['collect'],['audit'],['collect','collect']):
            with self.subTest(stages=stages),tempfile.TemporaryDirectory() as directory:
                study=Path(directory)
                P.write(study/'learning-registration.json',{'runner_sha256':P.sha(P.__file__),
                    'hashes':{str(P.__file__):P.sha(P.__file__)}})
                P.write(study/'data-execution-completion.json',{'status':'complete','stages':[{'name':s} for s in stages]})
                with self.assertRaisesRegex(ValueError,'missing or duplicate collection/audit phase'):P.admit(study)
                self.assertFalse((study/'training-execution').exists())


@unittest.skipUnless(os.environ.get('E133_STUDY'),'requires prepared E133 runtime')
class NativeEarlyExperimentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.study=Path(os.environ['E133_STUDY'])
        cls.E,cls.x,cls.N,cls.V=P.modules(cls.study)
        cls.trees=P.read(cls.study/'data/reused-trees.json')
        refs={r['seed']:r for r in P.read(cls.study/'data/references.json')}
        cls.refs=[refs[t['seed']] for t in cls.trees]
        rs,cs=cls.N.supports(cls.trees)
        base=cls.x.H.torch.load(cls.study/'data/runtime/model.pt',weights_only=True,map_location='cpu')
        artifact=cls.N.artifact_for(base,rs,cs,{})
        cls.zero=cls.N.EarlyCardPolicy(artifact)
        cls.checkpoint=cls.N.checkpoint(cls.zero,artifact,0)

    def test_independent_natural_audit_preserves_fixed_zero_head_routes(self):
        for tree in self.trees[:4]:
            source=P.read(tree['card_root']['source_path'])
            result=P.audit_route(self.x,self.V,source,self.checkpoint)
            self.assertEqual(result['status'],source['status'])
            self.assertEqual(result['terminal_fingerprint'],source['terminal_fingerprint'])

    def test_unscoped_action_change_is_rejected(self):
        source=P.read(self.trees[0]['card_root']['source_path'])
        changed=copy.deepcopy(source)
        step=next(s for s in changed['prefix'] if s['kind']=='outside')
        step['action']^=1
        with self.assertRaisesRegex(ValueError,'independent outside NN choice differs'):
            P.audit_route(self.x,self.V,changed,self.checkpoint)
        with self.assertRaisesRegex(ValueError,'first change is outside'):P.first_change(self.x,source,changed)
        self.assertEqual(P.first_change(self.x,source,source),{'kind':'unchanged'})
        scoped=copy.deepcopy(source);tree=self.trees[0]
        card=tree['card_root'];candidate=next(c for c in card['candidates'] if c!=card['chosen'])
        scoped['prefix'][card['prefix_index']]['action']=card['actions'][candidate]
        self.assertEqual(P.first_change(self.x,source,scoped)['kind'],'first_act_one_card')

    def test_live_choice_worker_accepts_correct_leaf_and_rejects_changed_target(self):
        tree=self.trees[0];refs=[self.refs[0]]
        data=self.N.pack([tree],refs,self.checkpoint['relic_support'],self.checkpoint['card_support'])
        expected=self.N.deterministic_outcomes(self.zero,data)[0]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').symlink_to(self.study/'data',target_is_directory=True)
            (root/'learning').mkdir();model=root/'learning/candidate.pt'
            self.x.H.torch.save(self.checkpoint,model)
            job={'seed':tree['seed'],'study':str(root),'tree':tree,'expected':expected,
                 'checkpoint_sha256':P.sha(model),'output':str(root/'correct.json')}
            P.choice_worker(job,self.x.config)
            result=P.read(job['output']);self.assertEqual(result['status'],'complete',result)
            self.assertEqual(result['target'],expected['target'])
            bad=copy.deepcopy(job);bad['expected']['target']=1-expected['target'];bad['output']=str(root/'wrong.json')
            P.choice_worker(bad,self.x.config)
            result=P.read(bad['output']);self.assertEqual(result['status'],'choice_error')
            self.assertIn('selected terminal differs',result['error'])

    def test_frozen_first_head_cannot_use_joint_only_winner(self):
        # A controlled analytic tree, not an empirical game or new candidate.
        tree=copy.deepcopy(self.trees[0]);root=tree['card_root']
        chosen=root['chosen'];other=next(c for c in root['candidates'] if c!=chosen)
        template=next(b['boss_root'] for b in tree['branches'] if b['boss_root'] is not None)
        for branch in tree['branches']:
            boss=copy.deepcopy(template);boss['id']=f'analytic-{branch["card_candidate"]}'
            boss['early_card_candidate']=branch['card_candidate'];branch['boss_root']=boss
            branch['parent_target']=0
            alternative=next(c for c in boss['candidates'] if c!=boss['chosen'])
            branch['leaves']=[{'candidate':c,'target':int(branch['card_candidate']==other and c==alternative)} for c in boss['candidates']]
        refs=[dict(self.refs[0],status='death',target=0)]
        data=self.N.pack([tree],refs,self.checkpoint['relic_support'],self.checkpoint['card_support'])
        artifact=dict(self.checkpoint,change_card=False)
        policy=self.N.EarlyCardPolicy(artifact)
        self.assertEqual(float(self.N.mean_terminal_return(policy,data).detach()),0.)


if __name__=='__main__':unittest.main()
