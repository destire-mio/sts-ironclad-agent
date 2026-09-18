"""Replay real natural Heart wins, including the floor-55 Secret Portal route."""
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
import heart_acceptance as V
import heart_audit as D
import heart_bulk_collect as B
import heart_role_teacher as T
import heart_train_target as W

H, R = V.H, V.R
FIXTURES = REPO / 'tests/fixtures'


class PortalValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.torch.set_num_threads(1)
        cls.config = {'ascension': 20, 'policy_start_floor': 0, 'seconds_per_floor': 45}
        cls.runs = [H.read_json(FIXTURES / name) for name in (
            'heart-portal-101890269.json.gz', 'heart-ordinary-1045458017.json.gz')]
        for run in cls.runs:
            gc = R.replay(run['seed'], run['prefix'], cls.config)
            actual = R.fingerprint(gc)
            if 'terminal_fingerprint' in run:
                assert run['terminal_fingerprint'] == actual
            run['terminal_fingerprint'] = actual
        cls.teacher = T.RoleTeacher(1)

    def test_real_portal_skips_two_rooms_before_the_double_boss(self):
        run = self.runs[0]
        gc = R.replay(run['seed'], run['prefix'][:208], self.config)
        self.assertEqual((gc.event_id_string, gc.floor_num, gc.cur_map_node_y),
                         ('SecretPortal', 47, 12))
        R.replay_step(gc, run['prefix'][208], self.config)
        self.assertEqual((gc.floor_num, gc.cur_map_node_y, gc.encounter),
                         (48, 15, R.sts.MonsterEncounter.AWAKENED_ONE))
        self.assertEqual((run['floor'], run['hp'], run['keys']), (55, 56, [True] * 3))
        self.assertEqual(self.runs[1]['floor'], 57)

    def test_training_encodes_both_natural_winning_routes(self):
        for run in self.runs:
            with self.subTest(floor=run['floor']):
                groups = R.training_samples(run, self.config)
                self.assertTrue(groups)
                self.assertEqual({row['seed'] for row in groups}, {run['seed']})

    def test_training_rejects_changed_floor_keys_hp_and_terminal_rng(self):
        for field, value in (('floor', 57), ('keys', [False, True, True]),
                             ('hp', 57), ('terminal_fingerprint', 'changed-rng')):
            with self.subTest(field=field):
                run = {**self.runs[0], field: value}
                with self.assertRaisesRegex(ValueError, 'terminal'):
                    R.training_samples(run, self.config)

    def test_training_target_verifies_teacher_choices_on_both_routes(self):
        for run in self.runs:
            with self.subTest(floor=run['floor']):
                result = W.verify_policy_win(run, self.teacher, self.config)
                self.assertTrue(result['passed'])
                self.assertGreater(result['network_decisions'], 0)

    def test_branch_audit_replays_the_portal_win(self):
        run = self.runs[0]
        before_heart = R.replay(run['seed'], run['prefix'][:-2], self.config)
        actions = list(R.sts.get_legal_game_actions(before_heart))
        self.assertEqual(len(actions), 1)
        _, descriptors, _ = H.A.build_choices(before_heart)
        root_state = {'seed': run['seed'], 'fingerprint': R.fingerprint(before_heart),
                      'actions': [int(actions[0].bits)], 'descriptors': descriptors, 'chosen': 0}
        outcome = {k: run[k] for k in ('seed', 'status', 'target', 'act', 'floor', 'hp', 'keys')}
        outcome['candidate'] = 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace = root / 'success.json.gz'
            H.write_json(trace, run)
            H.write_json(root / 'config.json', self.config)
            H.write_json(root / 'seeds.json', {'train': [run['seed']], 'validation': [], 'final_test': []})
            H.write_json(root / 'manifest.json', {'frozen_files': {
                name: V.sha(root / name) for name in ('config.json', 'seeds.json')}})
            H.write_json(root / 'branches/train/win.json.gz', {
                'seed': run['seed'], 'status': 'complete', 'successes': [str(trace)],
                'groups': [{'root': root_state, 'outcomes': [outcome], 'complete': True, 'mixed': False}]})
            with patch.object(sys, 'argv', ['heart_audit', str(root), str(root / 'audit.json')]), \
                 patch.dict(os.environ), patch.object(sys, 'path', list(sys.path)):
                D.main()
            report = H.read_json(root / 'audit.json')
            self.assertTrue(report['passed'])
            self.assertEqual(report['splits']['train']['successful_replays'][0]['floor'], 55)

    def acceptance_directory(self, root, run):
        H.write_json(root / 'config.json', self.config)
        H.write_json(root / 'seeds.json', {'acceptance': [run['seed']],
                                         'training_or_development': []})
        (root / 'model.pt').write_bytes(b'test-only role teacher loader')
        H.write_json(root / 'manifest.json', {'frozen_files': {
            name: V.sha(root / name) for name in ('config.json', 'seeds.json', 'model.pt')}})
        H.write_json(root / f"episodes/{run['seed']}.json.gz", run)

    def test_acceptance_replays_both_routes_without_a_fixed_floor_requirement(self):
        for run in self.runs:
            with self.subTest(floor=run['floor']), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.acceptance_directory(root, run)
                # These unit tests exercise real action/state/RNG replay. MCTS was
                # used to collect the fixtures, rather than rerun for each assertion.
                with patch.object(V, 'load_policy', return_value=self.teacher), \
                     patch.object(R, 'rollout', return_value=copy.deepcopy(run)):
                    result = V.verify_win(root, run['seed'])
                self.assertTrue(result['passed'])
                self.assertEqual(result['floor'], run['floor'])

    def test_acceptance_rejects_wrong_floor_missing_keys_and_wrong_act(self):
        for field, value in (('floor', 57), ('keys', [False, True, True]), ('act', 3)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                run = {**self.runs[0], field: value}
                self.acceptance_directory(root, run)
                with patch.object(V, 'load_policy', return_value=self.teacher), \
                     patch.object(R, 'rollout', return_value=copy.deepcopy(self.runs[0])):
                    with self.assertRaises(ValueError):
                        V.verify_win(root, run['seed'])

    def test_collector_keeps_raw_actions_when_validation_fails(self):
        run = copy.deepcopy(self.runs[0])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = {'directory': str(root), 'seed': run['seed'], 'output': str(root / 'result.json')}
            with patch.object(R, 'rollout', return_value=run), \
                 patch.object(R, 'training_samples', side_effect=ValueError('validation failed')), \
                 patch.object(H.torch, 'set_num_interop_threads'):
                B.worker(job, self.config)
            trace = H.read_json(root / f"episodes/{run['seed']}.json.gz")
            self.assertEqual(trace['prefix'], run['prefix'])
            self.assertEqual(trace['terminal_fingerprint'], run['terminal_fingerprint'])
            result = H.read_json(root / 'result.json')
            self.assertEqual(result['status'], 'data_error')
            self.assertFalse(result['replay_verified'])
            self.assertIsNone(result['target'])
            self.assertFalse((root / f"encoded/{run['seed']}.json.gz").exists())


if __name__ == '__main__':
    unittest.main()
