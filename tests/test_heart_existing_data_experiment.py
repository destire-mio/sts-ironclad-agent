"""E134 native representation and reuse contracts; no new simulated games."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('E134_STUDY'), 'requires prepared E134 data/runtime')
class ExistingDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['E134_STUDY'])
        path = cls.root/'program/heart_existing_data_experiment.py'
        spec = importlib.util.spec_from_file_location('e134_test_runner', path)
        cls.E = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.E)
        cls.L, cls.N, cls.V = cls.E.modules(cls.root)
        cls.plan = cls.E.read(cls.root/'protocol.json')
        cls.bundle = cls.E.read(cls.root/'inputs.json.gz')
        old = cls.L.torch.load(cls.plan['control_checkpoint'], weights_only=True, map_location='cpu')
        cls.artifact = cls.N.artifact(old['base_checkpoint'], old['relic_support'], old['card_support'], {})
        cls.zero = cls.N.ExplicitReadoutPolicy(cls.artifact)
        cls.checkpoint = {**cls.artifact, **cls.L.head_states(cls.zero)}
        # Assigned order, first four naturally eligible fit trees, no win filter.
        cls.trees = [t for t in cls.bundle['trees'] if t['split']=='fit'][:4]
        cls.config = cls.E.read(cls.root/'runtime/config.json')

    def states(self):
        for tree in self.trees:
            yield 'relic', tree['boss_root']
            for branch in tree['branches']:
                if branch['card_root'] is not None:
                    yield 'card', self.bundle['states'][branch['card_root']]

    def restore(self, state):
        source = self.E.read(state['source_path'])
        gc = self.V.R.replay(state['seed'], source['prefix'][:state['prefix_index']], self.config)
        self.assertEqual(self.V.R.fingerprint(gc), state['fingerprint'])
        return gc

    def test_declared_roles_match_original_and_keep_complete_denominators(self):
        roles = self.E.read(self.root/'roles.json')
        self.assertEqual({k:len(v) for k,v in roles.items()}, {'fit':1536,'label_holdout':1024})
        self.assertFalse(set(roles['fit']) & set(roles['label_holdout']))
        for role, seeds in roles.items():
            self.assertEqual([r['seed'] for r in self.bundle['references'] if r['split']==role], seeds)
        self.assertEqual(self.plan['new_sampling_budget'], 0)

    def test_loader_parameter_budget_and_zero_head_preserve_parent_routes(self):
        loaded = self.L.H.load_scorer(self.checkpoint)
        self.assertEqual(loaded.model_type, 'explicit_joint_readout')
        self.assertEqual(sum(p.numel() for p in loaded.parameters() if p.requires_grad), 472)
        self.assertTrue(all(not p.requires_grad for p in loaded.base.parameters()))
        count = 0
        for tree in self.trees:
            row = self.E.read(tree['boss_root']['source_path'])
            gc = self.V.R.sts.GameContext(self.V.R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
            for step in row['prefix']:
                self.V.R.clock_input(gc, self.config)
                if step['kind']=='outside':
                    actions = list(self.V.R.sts.get_legal_game_actions(gc)); _, desc, _ = self.V.A.build_choices(gc)
                    choice = loaded.choose(gc, self.V.A.obs_vec(gc), actions, desc)
                    self.assertEqual(int(actions[choice].bits), step['action']); count += 1
                self.V.R.replay_step(gc, step, self.config)
            self.V.R.clock_input(gc, self.config); self.V.P.verify_terminal(gc, row)
        self.assertGreater(count, 100)

    def test_nonzero_heads_match_independent_native_state_and_action_decoder(self):
        checkpoint = copy.deepcopy(self.checkpoint)
        for stage in ('relic','card'):
            head = checkpoint[stage+'_state']
            head['weight'].copy_(self.L.torch.linspace(-.4, .7, 192))
            head['static_scores'].copy_(self.L.torch.linspace(-.3, .3, len(head['static_scores'])))
        policy = self.L.H.load_scorer(checkpoint); seen = set()
        for stage, state in self.states():
            self.E.native_decision(self.N, self.V, policy, checkpoint, self.restore(state), stage)
            seen.add(stage)
        self.assertEqual(seen, {'card','relic'})

    def test_map_and_unused_observation_fields_do_not_enter_explicit_features(self):
        torch = self.L.torch; A = self.V.A
        _, state = next(self.states()); gc = self.restore(state)
        _, desc, _ = A.build_choices(gc)
        observations = torch.tensor([A.obs_vec(gc)]*len(desc)); descriptors = torch.tensor(desc)
        actual = self.zero.embed(observations, descriptors)
        retained = {0,1,*range(self.N.DECK_OFFSET,self.N.DECK_OFFSET+2*A.CARD_CAP),
                    self.N.RELIC_OFFSET+int(self.V.R.sts.RelicId.DEAD_BRANCH)}
        changed = observations.clone()
        changed[:, [i for i in range(A.OBS_DIM) if i not in retained]] = 9.
        self.assertTrue(torch.equal(actual, self.zero.embed(changed,descriptors)))

    def test_exhaust_relic_interaction_changes_only_the_declared_feature(self):
        torch = self.L.torch; A = self.V.A
        observation = torch.zeros((1,A.OBS_DIM)); observation[0,1]=.4
        count_slot = self.N.DECK_OFFSET+2*int(self.V.R.sts.CardId.DEFEND_RED)
        observation[0,count_slot] = 5/20
        descriptor = torch.zeros((1,A.DESC_DIM))
        descriptor[0,A.AK_REWARD_CARD] = 1
        descriptor[0,A.OFF_CARD+int(self.V.R.sts.CardId.BURNING_PACT)] = 1
        before = self.zero.embed(observation,descriptor).reshape(12,16)
        observation[0,self.N.RELIC_OFFSET+int(self.V.R.sts.RelicId.DEAD_BRANCH)] = 1
        after = self.zero.embed(observation,descriptor).reshape(12,16)
        self.assertEqual(float(after[5,15]-before[5,15]),1.)
        self.assertTrue(torch.equal(before[:,:15],after[:,:15]))

    def test_unknown_whole_offer_keeps_parent_and_zero_sources_are_not_relabelled(self):
        gc = self.restore(self.trees[0]['boss_root'])
        actions = list(self.V.R.sts.get_legal_game_actions(gc)); _, desc, _ = self.V.A.build_choices(gc)
        offered = {self.L.J.relic_option(d) for d in desc}; offered.discard(None)
        artifact = copy.deepcopy(self.artifact)
        artifact['relic_support'] = [x for x in artifact['relic_support'] if x!=next(iter(offered))]
        policy = self.N.ExplicitReadoutPolicy(artifact)
        with self.L.torch.no_grad(): policy.relic.static_scores.fill_(50.)
        obs = self.V.A.obs_vec(gc)
        self.assertEqual(policy.choose(gc,obs,actions,desc),policy.base.choose(gc,obs,actions,desc))
        seeds = {t['seed'] for t in self.bundle['trees']}
        ref = next(r for r in self.bundle['references'] if r['seed'] not in seeds)
        row = {'seed':ref['seed'],'no_intervention':True}
        self.assertEqual(self.E.independent_leaf(None,row,self.bundle),int(ref['status']=='heart_win'))

    def test_closed_or_incomplete_study_rejects_before_learning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError): self.E.train(root)
            (root/'source-closed.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'closed'): self.E.train(root)
            self.assertFalse((root/'learning').exists())

    def test_worker_accepts_actual_selected_leaf_and_rejects_wrong_terminal(self):
        tree = self.trees[0]
        branch = next(b for b in tree['branches'] if b['relic_candidate']==tree['boss_root']['chosen'])
        child = self.bundle['states'].get(branch['card_root'])
        expected = {'seed':tree['seed'],'target':int(branch['parent_target']),
            'relic_candidate':tree['boss_root']['chosen'], 'no_intervention':False,
            'card':None if child is None else {'root_id':child['id'],'candidate':child['chosen']}}
        keys = [b['card_root'] for b in tree['branches'] if b['card_root'] is not None]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'runtime').symlink_to(self.root/'runtime',target_is_directory=True)
            (root/'learning').mkdir(); path = root/'learning/candidate.pt'
            self.L.torch.save(self.checkpoint,path)
            job = {'root':str(root),'seed':tree['seed'],'tree':tree,'expected':expected,
                'states':{k:self.bundle['states'][k] for k in keys},
                'labels':{k:self.bundle['labels'][k] for k in keys},
                'checkpoint_sha256':self.E.sha(path),'output':str(root/'valid.json')}
            self.E.choice_worker(job,self.config)
            self.assertEqual(self.E.read(job['output'])['status'],'complete',self.E.read(job['output']))
            wrong = copy.deepcopy(job); wrong['expected']['target'] ^= 1
            wrong['output'] = str(root/'wrong.json')
            self.E.choice_worker(wrong,self.config)
            self.assertEqual(self.E.read(wrong['output'])['status'],'verification_error')


if __name__=='__main__': unittest.main()
