"""Frozen-encoder joint learning: behavior, isolation and selection contracts."""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

AGENT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT))
import test_heart_relic_card_training as fixtures
import heart_relic_card_readout as M
import heart_relic_card_readout_training as T
import heart_relic_card_development as D

L, H, R, torch = T.L, T.H, M.R, T.torch


def many_families():
    trees, states, labels, refs = [], {}, {}, []
    used = set()
    for held in range(3):
        seeds = [s for s in range(100, 200) if T.fold(s) == held][:3]
        for seed in seeds[:2]:
            t, s, y, _, rs, cs = copy.deepcopy(fixtures.fixture())
            t[0].update(seed=seed, split='fit')
            t[0]['boss_root'].update(id=f'boss-{seed}', seed=seed)
            for branch in t[0]['branches']:
                old = branch['card_root']; new = f'{old}-{seed}'
                branch['card_root'] = new
                s[old].update(id=new, seed=seed)
                states[new], labels[new] = s[old], y[old]
            trees.extend(t); refs.append({'seed': seed, 'split': 'fit', 'status': 'death'})
        refs.append({'seed': seeds[2], 'split': 'fit', 'status': 'death'})
        used.update(seeds)
    assert len(used) == 9
    return trees, states, labels, refs, rs, cs


class ReadoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.runtime = Path(os.environ['HEART_BRANCH_RUNTIME'])
        cls.base = torch.load(cls.runtime / 'model.pt', weights_only=True, map_location='cpu')

    def policy(self, arm='joint'):
        *_, rs, cs = fixtures.fixture()
        return M.ReadoutPolicy(T.artifact_for(self.base, rs, cs, arm, {}))

    def test_zero_heads_keep_parent_and_unknown_offer_has_finite_gradients(self):
        values = fixtures.fixture(); data = L.pack(*values); policy = self.policy()
        self.assertEqual([r['target'] for r in L.deterministic_outcomes(policy, data)], [0, 0])
        # Parent margin1 means the only winning two-change branch has p=(1/(e+1))^2.
        expected = 1. / (1. + torch.e) ** 2 / 2.
        self.assertAlmostEqual(float(L.mean_terminal_return(policy, data).detach()), expected)
        restricted = [values[-1][0]]
        data = L.pack(*values[:-1], restricted)
        artifact = T.artifact_for(self.base, values[-2], restricted, 'joint', {})
        policy = M.ReadoutPolicy(artifact)
        loss, reward = T.objective(policy, data, .001); loss.backward()
        self.assertEqual(float(reward.detach()), 0.)
        self.assertTrue(all(p.grad is None or torch.isfinite(p.grad).all() for p in policy.parameters()))

    def test_joint_training_learns_and_cannot_mutate_pretrained_encoder(self):
        values = fixtures.fixture(); data = L.pack(*values)
        artifact = T.artifact_for(self.base, values[-2], values[-1], 'joint', {})
        policy, _ = T.fit(artifact, data, {'steps': 180, 'learning_rate': .03, 'gradient_norm': 1.}, .0001)
        self.assertEqual([r['target'] for r in L.deterministic_outcomes(policy, data)], [1, 0])
        T.same_state(H.load_scorer(self.base).state_dict(), policy.base.state_dict())
        self.assertTrue(all(not p.requires_grad and p.grad is None for p in policy.base.parameters()))
        self.assertEqual(sum(p.numel() for p in policy.parameters() if p.requires_grad), 388)
        for arm in ('relic', 'card'):
            self.assertEqual(float(L.mean_terminal_return(self.policy(arm), data).detach()), 0.)

    def test_family_splits_include_early_failures_and_exclude_validation_support(self):
        values = many_families(); data = L.pack(*values)
        for held in range(3):
            train_seeds = {r['seed'] for r in values[3] if T.fold(r['seed']) != held}
            val_seeds = {r['seed'] for r in values[3] if T.fold(r['seed']) == held}
            train, rs, cs = T.split_data(data, train_seeds)
            validation, _, _ = T.split_data(data, val_seeds, (rs, cs))
            self.assertEqual(train['assigned'], 6); self.assertEqual(validation['assigned'], 3)
            self.assertFalse({r['seed'] for r in train['card']['rows']} & val_seeds)
            self.assertFalse({r['seed'] for r in validation['card']['rows']} & train_seeds)
            self.assertEqual(len(validation['trees']), 2)
        data['references'][0]['split'] = 'label_holdout'
        with self.assertRaises(ValueError): T.split_data(data, {data['references'][0]['seed']})

    def test_validation_features_do_not_enter_support_or_normalization(self):
        values = many_families(); seed = values[0][0]['seed']
        held = T.fold(seed)
        # A card seen only in validation must be unknown to that training fold.
        extra = int(R.sts.CardId.BASH)
        for row in values[1].values():
            if T.fold(row['seed']) == held:
                row['option_ids'][1] = extra
                desc = R.dense(row['descriptors'][1], M.A.DESC_DIM)
                desc[M.A.OFF_CARD:M.A.OFF_CARD + M.A.W_CARD] = [0.] * M.A.W_CARD
                desc[M.A.OFF_CARD + extra] = 1.
                row['descriptors'][1] = R.sparse(desc)
        data = L.pack(*values[:-1], values[-1] + [extra])
        train_seeds = {r['seed'] for r in values[3] if T.fold(r['seed']) != held}
        train, rs, cs = T.split_data(data, train_seeds)
        self.assertNotIn(extra, cs)
        policy = M.ReadoutPolicy(T.artifact_for(self.base, rs, cs, 'joint', {}))
        policy.training_logits(train)
        policy.card.fit_scale(train['card']['readout_embeddings'], train['card']['mask'])
        before = policy.card.scale.clone()
        validation, _, _ = T.split_data(data, {r['seed'] for r in values[3]} - train_seeds, (rs, cs))
        self.assertFalse(validation['card']['allowed'].any())
        for row in validation['card']['rows']: row['observation'] = R.sparse([100.] * M.A.OBS_DIM)
        policy.training_logits(validation)
        self.assertTrue(torch.equal(before, policy.card.scale))

    def test_internal_selection_falls_back_and_ties_prefer_stronger_penalty(self):
        def report(l2, wins, lost, p):
            return {'l2': l2, 'outcomes': {'candidate_wins': wins, 'net_gain': wins-10,
                    'exact_p': p, 'paired': {'baseline_only': lost}}}
        self.assertIsNone(T.select_trial([report(.001, 11, 2, .5)], 10, .05))
        self.assertEqual(T.select_trial([report(.001, 22, 2, .01), report(.01, 22, 2, .01)], 10, .05), .01)
        values = many_families(); data = L.pack(*values)
        cfg = {'steps': 1, 'learning_rate': .03, 'gradient_norm': 1., 'folds': 3,
               'l2_grid': [.001], 'cv_minimum_net_gain': 10, 'cv_p_maximum': .05}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = T.train_arm(root, 'joint', data, self.base, values[-2], values[-1], cfg, {})
            self.assertTrue(artifact['parent_fallback']); self.assertEqual(artifact['optimizer_updates'], 0)
            H.write_json(root / 'protocol.json', {'training': cfg})
            T.verify_selection(root, 'joint', *values[:4], self.base)
            proof = H.read_json(root / 'joint/selection-verification.json')
            self.assertEqual(proof['fit_families'], 9)
            report = H.read_json(root / 'joint/cv-0.001.json')
            report['folds'][0]['fit_seeds'].append(report['folds'][0]['validation_seeds'][0])
            H.write_json(root / 'joint/cv-0.001.json', report)
            with self.assertRaises(AssertionError): T.verify_selection(root, 'joint', *values[:4], self.base)
        cfg['cv_minimum_net_gain'] = 1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = T.train_arm(root, 'joint', data, self.base, values[-2], values[-1], cfg, {})
            self.assertFalse(artifact['parent_fallback']); self.assertEqual(artifact['optimizer_updates'], 1)
            H.write_json(root / 'protocol.json', {'training': cfg})
            T.verify_selection(root, 'joint', *values[:4], self.base)

    def test_production_loader_and_live_zero_queries_match_parent(self):
        config = H.read_json(self.runtime / 'config.json')
        # Reconstruct with this runtime's own episodes; old-engine fingerprints
        # are not fixtures for a newly repaired runtime.
        natural = self.runtime
        if not (natural / 'episodes').is_dir():
            natural = Path(H.read_json(natural / 'protocol.json')['natural_source'])
        parent_policy = H.load_scorer(self.base)
        boss = None
        for path in sorted((natural / 'episodes').glob('*.json.gz')):
            episode = H.read_json(path)
            self.assertEqual(episode['engine_sha256'], L.B.S.sha(R.sts.__file__))
            self.assertEqual(episode['checkpoint_sha256'], L.B.S.sha(self.runtime / 'model.pt'))
            boss = L.B.first_root(episode, path, 'fit', config, parent_policy)
            if boss is not None:
                break
        self.assertIsNotNone(boss, 'runtime needs a naturally reached first-boss fixture')
        gc = R.replay(boss['seed'], episode['prefix'][:boss['prefix_index']], config)
        actions = list(R.sts.get_legal_game_actions(gc)); _, desc, _ = M.A.build_choices(gc)
        observation = M.A.obs_vec(gc)
        artifact = T.artifact_for(self.base, boss['option_ids'], fixtures.fixture()[-1], 'joint', {})
        policy = M.ReadoutPolicy(artifact); before = R.fingerprint(gc)
        parent = policy.base.choose(gc, observation, actions, desc)
        for _ in range(3): self.assertEqual(policy.choose(gc, observation, actions, desc), parent)
        self.assertEqual(before, R.fingerprint(gc))
        artifact.update(**T.head_states(policy))
        spec = importlib.util.spec_from_file_location('production_readout_loader', AGENT / 'heart_train.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        loaded = module.load_scorer(artifact)
        self.assertEqual(loaded.choose(gc, observation, actions, desc), parent)
        # Native choices plus direct weight arithmetic agree with deployed scoring.
        ids = {i: M.A.RELIC_CAP if a.idx1 == 3 else int(gc.boss_relics[a.idx1])
               for i, a in enumerate(actions) if not a.is_potion_action}
        with torch.no_grad():
            policy.relic.weight.copy_(torch.linspace(-.02, .02, 192))
            policy.relic.static_scores[-1] = 2.
        artifact.update(**T.head_states(policy))
        self.assertEqual(policy.choose(gc, observation, actions, desc),
            D.readout_native_choice(policy.base, artifact, 'relic', observation, desc, ids, parent))


if __name__ == '__main__': unittest.main()
