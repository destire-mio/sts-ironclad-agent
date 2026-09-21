"""E133 deployment checks using fixed existing fit traces; no new games."""
import copy
import importlib
import importlib.util
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('E133_STUDY'), 'requires prepared E133 runtime')
class EarlyLearningNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['E133_STUDY'])/'data'
        spec=importlib.util.spec_from_file_location('scope_native_probe',
            cls.root/'runtime/heart_early_card_scope.py')
        cls.E=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.E)
        cls.x=cls.E.load_runtime(cls.root/'runtime')
        cls.N=importlib.import_module('heart_early_card_learning')
        cls.D=importlib.import_module('heart_relic_card_development')
        cls.parent=cls.E.parent_model(cls.x)
        trees=cls.E.read(cls.root/'reused-trees.json')
        cls.trees=trees[:4]  # original role order, before reading outcomes
        rs,cs=cls.N.supports(trees)
        cls.base=cls.x.H.torch.load(cls.root/'runtime/model.pt',weights_only=True,map_location='cpu')
        cls.artifact=cls.N.artifact_for(cls.base,rs,cs,{})
        cls.zero=cls.N.EarlyCardPolicy(cls.artifact)
        cls.checkpoint=cls.N.checkpoint(cls.zero,cls.artifact,0)
        cls.loaded=cls.x.H.load_scorer(cls.checkpoint)

    def test_registered_loader_and_zero_heads_preserve_full_parent_routes(self):
        x=self.x;count=0
        self.assertEqual(self.loaded.model_type,'early_card_relic_readout')
        for tree in self.trees:
            source=self.E.read(tree['card_root']['source_path'])
            gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,source['seed'],20)
            for step in source['prefix']:
                x.R.clock_input(gc,x.config)
                if step['kind']=='outside':
                    actions=list(x.R.sts.get_legal_game_actions(gc));_,desc,_=x.A.build_choices(gc)
                    obs=x.A.obs_vec(gc);before=x.R.fingerprint(gc)
                    chosen=self.loaded.choose(gc,obs,actions,desc)
                    self.assertEqual(chosen,self.parent.choose(gc,obs,actions,desc))
                    self.assertEqual(int(actions[chosen].bits),step['action'])
                    self.assertEqual(x.R.fingerprint(gc),before);count+=1
                x.R.replay_step(gc,step,x.config)
            x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,source)
        self.assertGreater(count,100)

    def test_nonzero_card_and_relic_heads_match_native_option_arithmetic(self):
        x=self.x;seen=set()
        for tree in self.trees:
            states=[('card',tree['card_root'])]+[('relic',b['boss_root']) for b in tree['branches'] if b['boss_root'] is not None]
            for stage,state in states:
                row=self.E.read(state['source_path'])
                gc=x.R.replay(state['seed'],row['prefix'][:state['prefix_index']],x.config)
                actions=list(x.R.sts.get_legal_game_actions(gc));_,desc,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
                self.assertEqual(x.R.fingerprint(gc),state['fingerprint'])
                candidate=next(c for c in state['candidates'] if c!=state['chosen'])
                identity=self.N.J.card_option if stage=='card' else self.N.J.relic_option
                checkpoint=copy.deepcopy(self.checkpoint)
                position=checkpoint[stage+'_support'].index(identity(desc[candidate]))
                checkpoint[stage+'_state']['static_scores'][position]=3.
                loaded=x.H.load_scorer(checkpoint)
                if stage=='card':
                    options={i:v[0] for i,v in self.D.native_card_options(gc,actions).items()}
                else:
                    options={i:(x.A.RELIC_CAP if action.idx1==3 else int(gc.boss_relics[action.idx1]))
                             for i,action in enumerate(actions) if not action.is_potion_action}
                expected=self.D.readout_native_choice(self.parent,checkpoint,stage,obs,desc,options,state['chosen'])
                before=x.R.fingerprint(gc)
                self.assertEqual(loaded.choose(gc,obs,actions,desc),expected)
                self.assertEqual(expected,candidate)
                self.assertEqual(loaded.choose(gc,obs,actions,desc),expected)
                self.assertEqual(x.R.fingerprint(gc),before);seen.add(stage)
        self.assertEqual(seen,{'card','relic'})

    def test_packed_zero_choices_match_the_original_complete_fit_trees(self):
        references={r['seed']:r for r in self.E.read(self.root/'references.json')}
        refs=[references[t['seed']] for t in self.trees]
        data=self.N.pack(self.trees,refs,self.artifact['relic_support'],self.artifact['card_support'])
        choices=self.N.deterministic_outcomes(self.loaded,data)
        self.assertEqual([c['target'] for c in choices],[int(r['status']=='heart_win') for r in refs])
        self.assertEqual([c['card_candidate'] for c in choices],[t['card_root']['chosen'] for t in self.trees])


if __name__=='__main__':unittest.main()
