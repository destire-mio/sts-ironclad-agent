"""Freeze completed games, retain pending reservations, and reject changed sources."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
import heart_data_snapshot as D
import heart_stream_train as S


class DataSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.config = S.H.read_json(REPO / 'configs/heart_round1.json')
        self.config.update(simulations=50)
        self.seed = 9012345
        S.H.write_json(self.source / 'config.json', self.config)
        S.H.write_json(self.source / 'seeds.json', {'train': [self.seed, self.seed + 1]})
        S.H.write_json(self.source / 'status.json', {'stage': 'paused_by_request'})
        (self.source / 'engine').mkdir()
        module = Path(S.H.A.sts.__file__)
        shutil.copy2(module, self.source / 'engine' / module.name)
        S.H.write_json(self.source / 'manifest.json', {'frozen_files': {
            name: S.sha(self.source / name) for name in ('config.json', 'seeds.json')}})
        D.C.worker({'seed': self.seed, 'directory': str(self.source),
                    'output': str(self.source / f'results/{self.seed}.json')}, self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_includes_every_completed_game_and_preserves_unplayed_reservations(self):
        snapshot = self.root / 'snapshot'
        D.snapshot([self.source], snapshot)
        report = S.H.read_json(snapshot / 'report.json')
        self.assertEqual(report['requested'], 1)
        self.assertEqual(report['summary']['runs'], 1)
        self.assertEqual(report['unplayed_reserved_seeds_excluded'], 1)
        self.assertEqual(S.H.read_json(snapshot / 'seeds.json')['train'], [self.seed])
        self.assertEqual(S.H.read_json(self.source / 'seeds.json')['train'], [self.seed, self.seed + 1])
        self.assertFalse(report['sampling_goal_completed'])
        self.assertEqual(report['dataset_kind'], 'completed_attempt_snapshot')
        S.verify_files(snapshot)

    def test_active_collection_and_failed_result_do_not_enter_snapshot(self):
        S.H.write_json(self.source / 'status.json', {'stage': 'collecting'})
        with self.assertRaisesRegex(ValueError, 'stop collection'):
            D.snapshot([self.source], self.root / 'snapshot')
        S.H.write_json(self.source / 'status.json', {'stage': 'paused_by_request'})
        S.H.write_json(self.source / f'results/{self.seed}.json',
                     {'seed': self.seed, 'status': 'timeout', 'target': None, 'replay_verified': False})
        with self.assertRaisesRegex(ValueError, 'invalid result'):
            D.snapshot([self.source], self.root / 'snapshot')

    def test_assembly_rejects_result_mutation_after_cutoff(self):
        snapshot = self.root / 'snapshot'
        D.snapshot([self.source], snapshot)
        parent, fit = self.root / 'parent', self.root / 'fit'
        for name in ('train-warm', 'train-success'):
            S.H.write_json(parent / f'data/{name}.json.gz', [])
        S.H.write_json(parent / 'manifest.json', {'frozen_files': {}, 'training_success_paths': {}})
        S.H.write_json(fit / 'plan.json', {'data_parent': str(parent), 'collection': str(snapshot)})
        S.H.write_json(fit / 'seeds.json', {'train': [self.seed], 'validation': [], 'selected_development': []})
        S.H.write_json(fit / 'config.json', {'shard_size': 4})
        S.H.write_json(fit / 'queue-manifest.json', {'frozen_files': {}})
        result_path = self.source / f'results/{self.seed}.json'
        row = S.H.read_json(result_path)
        S.H.write_json(result_path, {**row, 'seconds': row['seconds'] + 1})
        with self.assertRaisesRegex(ValueError, 'changed after the training cutoff'):
            S.assemble(fit)


if __name__ == '__main__':
    unittest.main()
