"""Full-data training must update on every row, with no evaluation seed leakage."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
os.environ.setdefault('STS_LIGHTSPEED_BUILD', str(REPO.parent / 'ironclad-alignment/build'))
import heart_stream_train as S


class FullDataTrainingTest(unittest.TestCase):
    def setUp(self):
        S.H.torch.set_num_threads(1)

    def fixture(self, root):
        groups = [{'seed': i, 'observation': [], 'descriptors': [[], [[1, 1.0]]],
                   'teacher': 0, 'chosen': i % 2} for i in range(11)]
        writer = S.ShardWriter(root, size=3)
        writer.add(groups[:7])
        dataset = {'warm_shards': writer.finish(), 'warm_count': 7, 'success_count': 3,
                   'improved_count': 1, 'unique_decisions': 10}
        config = {'model_seed': 14, 'success_per_ordinary': 2.0, 'improved_per_ordinary': 0.5,
                  'batch_groups': 4}
        return dataset, groups[7:10], [groups[9]], config

    def test_every_record_reaches_training_once_even_with_partial_shards_and_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, positive, improved, config = self.fixture(root)
            orders = []
            for epoch in (1, 2):
                coverage = S.Coverage(7, 3, 1)
                batches = list(S.epoch_batches(root, data, positive, improved, config, epoch))
                ordinary = []
                for groups, identities, _ in batches:
                    # Verify the actual group, not just an invented coverage ID.
                    ordinary += [g['seed'] for g, identity in zip(groups, identities) if identity[0] == 'warm']
                    coverage.observe(identities)
                result = coverage.finish()
                self.assertEqual(sorted(ordinary), list(range(7)))
                self.assertEqual(result['unique_decisions_seen'], 10)
                self.assertEqual(result['exposures'], {'warm': 7, 'success': 14, 'improved': 4})
                self.assertTrue(any(len(groups) < 4 for groups, _, _ in batches))
                orders.append(ordinary)
            self.assertNotEqual(*orders)

    def test_missing_or_duplicate_ordinary_updates_cannot_claim_full_coverage(self):
        coverage = S.Coverage(2, 0, 0)
        coverage.observe([('warm', 0)])
        with self.assertRaisesRegex(ValueError, 'omitted'):
            coverage.finish()
        with self.assertRaisesRegex(ValueError, 'twice'):
            coverage.observe([('warm', 0)])

    def test_successes_all_visited_even_when_nominal_weight_would_omit_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, positive, improved, config = self.fixture(root)
            config.update(success_per_ordinary=0.01, improved_per_ordinary=0.01)
            coverage = S.Coverage(7, 3, 1)
            for _, identities, _ in S.epoch_batches(root, data, positive, improved, config, 1):
                coverage.observe(identities)
            self.assertEqual(coverage.finish()['exposures'], {'warm': 7, 'success': 3, 'improved': 1})

    def test_corrupt_shard_fails_before_becoming_training_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, positive, improved, config = self.fixture(root)
            (root / data['warm_shards'][0]['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'shard changed'):
                list(S.epoch_batches(root, data, positive, improved, config, 1))

    def test_evaluation_and_retired_test_seeds_cannot_be_added_to_training(self):
        roles = {'train': [1, 2], 'validation': [3], 'final_test': [4],
                 'retired_acceptance': [5], 'selected_development': [3]}
        S.validate_roles(roles)
        for seed in (3, 4, 5):
            bad = copy.deepcopy(roles)
            bad['train'].append(seed)
            with self.assertRaisesRegex(ValueError, 'overlap'):
                S.validate_roles(bad)
        bad = copy.deepcopy(roles)
        bad['selected_development'] = [6]
        with self.assertRaisesRegex(ValueError, 'outside'):
            S.validate_roles(bad)

    def test_resumed_optimizer_matches_uninterrupted_next_update(self):
        config = {'model_type': 'card_context_residual', 'arch': [8], 'prior_strength': 3.0,
                  'learning_rate': .00003, 'weight_decay': .00001}
        net = S.G.CardContextScorer((8,), 3.0)
        optimizer = S.H.torch.optim.AdamW(net.parameters(), lr=config['learning_rate'], weight_decay=config['weight_decay'])
        group = {'seed': 1, 'observation': [], 'descriptors': [[], [[1, 1.0]]], 'teacher': 0, 'chosen': 1}

        def step(n, o):
            o.zero_grad()
            loss = S.G.losses(n, [group])[0].mean()
            loss.backward()
            o.step()

        step(net, optimizer)
        initial = copy.deepcopy({**config, 'state_dict': net.state_dict(), 'optimizer': optimizer.state_dict()})
        restored, restored_optimizer = S.restore_training(initial, config)
        before = S.H.state_hash(net)
        step(net, optimizer)
        step(restored, restored_optimizer)
        self.assertEqual(S.H.state_hash(net), S.H.state_hash(restored))
        self.assertNotEqual(before, S.H.state_hash(restored))
        with self.assertRaisesRegex(ValueError, 'optimizer differs'):
            S.restore_training(initial, {**config, 'learning_rate': .003})

    def test_fresh_test_draw_excludes_training_and_tests_assigned_during_training(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'fit'
            root.mkdir()
            checkpoint = root / 'model.pt'
            checkpoint.write_bytes(b'frozen-model')
            S.H.write_json(root / 'seeds.json', {'train': [10000000], 'validation': [10000001],
                                                'legacy_exclusions': [10000002]})
            S.H.write_json(root.parent / 'other-test/seeds.json', {'acceptance': [10000003]})
            report = {'status': 'ready_for_fresh_seed_acceptance', 'new_updates': 10,
                      'best': {'checkpoint': str(checkpoint), 'checkpoint_sha256': S.sha(checkpoint),
                               'development': {'heart_wins': 3}}}

            def fake_acceptance(previous, model, destination, seed_file):
                frozen = S.H.read_json(previous / 'fresh-acceptance-plan.json')
                self.assertEqual(frozen['checkpoint_sha256'], S.sha(model))
                self.assertEqual(S.H.read_json(seed_file), [10000004, 10000005])
                S.H.write_json(destination / 'report.json', {'summary': {'runs': 2, 'valid_terminal': 2, 'heart_wins': 0}})

            with patch('heart_stream_train.secrets.randbelow', side_effect=range(6)), patch('heart_acceptance.launch', side_effect=fake_acceptance):
                S.accept_improved_model(root, report, {'fresh_acceptance_count': 2})
            self.assertEqual(report['status'], 'fresh_acceptance_complete')
            report['status'] = 'needs_training_improvement'
            with self.assertRaisesRegex(ValueError, 'gate has not passed'):
                S.accept_improved_model(root, report, {'fresh_acceptance_count': 2})

    def test_two_complete_passes_write_checkpoints_and_run_real_natural_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, positive, improved, sampling = self.fixture(root)
            config = {**S.H.read_json(REPO / 'configs/heart_round1.json'), **sampling,
                      'model_type': 'card_context_residual', 'arch': [8], 'prior_strength': 3.0,
                      'learning_rate': .00003, 'weight_decay': .00001,
                      'full_data_epochs': 2, 'torch_threads': 1, 'workers': 2,
                      'verified_development': True, 'refresh_development_baseline': True,
                      'checkpoint_every_updates': 2,
                      'simulations': 10, 'development_seconds': 120}
            net = S.G.CardContextScorer((8,), 3.0)
            optimizer = S.H.torch.optim.AdamW(net.parameters(), lr=config['learning_rate'], weight_decay=config['weight_decay'])
            initial = {**{k: config[k] for k in ('model_type', 'arch', 'prior_strength')},
                       'epoch': 8, 'updates': 2496, 'state_dict': net.state_dict(), 'optimizer': optimizer.state_dict()}
            S.H.torch.save(initial, root / 'initial.pt')
            roles = {'train': list(range(10)), 'validation': [9012345, 9012346],
                     'selected_development': [9012345, 9012346]}
            valid = {**positive[0], 'seed': 9012345}
            for name, value in [('config.json', config), ('seeds.json', roles), ('dataset.json', dataset),
                    ('data/train-success.json.gz', positive), ('data/train-improved.json.gz', improved),
                    ('data/validation-success.json.gz', [valid]), ('baseline.json', {'summary': {'heart_wins': 0}})]:
                S.H.write_json(root / name, value)
            S.H.write_json(root / 'manifest.json', {'frozen_files': {
                str(p.relative_to(root)): S.sha(p) for p in root.rglob('*') if p.is_file()}, 'parameters': sum(p.numel() for p in net.parameters())})
            S.fit(root)
            report = S.H.read_json(root / 'report.json')
            self.assertEqual(report['full_data_passes'], 2)
            self.assertEqual(len(report['evaluations']), 2)
            self.assertTrue(report['baseline']['refreshed_with_training_runtime'])
            self.assertTrue(S.H.read_json(root / 'baseline-refreshed.json')['summary']['complete'])
            for evaluation in report['evaluations']:
                self.assertEqual(evaluation['coverage']['unique_decisions_seen'], 10)
                self.assertEqual(evaluation['development']['valid_terminal'], 2)
                self.assertTrue(evaluation['development']['complete'])
            last = S.H.torch.load(root / 'models/last.pt', weights_only=True)
            self.assertEqual(last['updates'], 2496 + report['new_updates'])
            self.assertNotEqual(S.H.state_hash(net), last['state_hash'])
            progress = S.H.torch.load(root / 'models/progress.pt', weights_only=True)
            self.assertNotEqual(S.H.state_hash(net), progress['state_hash'])
            self.assertEqual(progress['full_data_passes'], progress['incomplete_epoch'] - 1)


if __name__ == '__main__':
    unittest.main()
