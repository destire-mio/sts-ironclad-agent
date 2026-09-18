"""Success quotas use distinct, replayed training seeds; faults never satisfy them."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
import heart_success_collect as S


class SuccessCollectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = json.loads((REPO / 'configs/heart_round1.json').read_text())
        self.config.update(workers=2)
        S.H.write_json(self.root / 'baseline-successes.json', [{'seed': 1}])
        S.H.write_json(self.root / 'seeds.json', {'train': [2, 3, 4]})
        self.plan = {'baseline_training_seeds': [1], 'target_successes': 3,
                     'baseline_successes': 1, 'baseline_games': 10, 'baseline_decisions': 100}

    def tearDown(self):
        self.temp.cleanup()

    def test_only_distinct_verified_wins_count_and_quota_stops_at_target(self):
        progress = S.Progress(self.root, self.plan, self.config)
        row = {'seed': 2, 'status': 'heart_win', 'target': 1.0, 'replay_verified': True,
               'terminal_state_verified': True, 'decision_count': 12}
        with patch.object(S, 'verify_success', side_effect=lambda root, seed, config: {'seed': seed}):
            self.assertFalse(progress.observe(row))
            self.assertFalse(progress.observe(row))
            self.assertEqual(len(progress.wins), 2)
            self.assertEqual(len(progress.seen), 1)
            self.assertTrue(progress.observe({**row, 'seed': 3}))
            self.assertEqual(len(progress.wins), 3)
            self.assertEqual(progress.decisions, 24)
        with self.assertRaisesRegex(ValueError, 'unassigned'):
            progress.observe({**row, 'seed': 99})

    def test_fault_or_unverified_win_stops_for_review_without_counting(self):
        for status in ('timeout', 'data_error', 'heart_win'):
            progress = S.Progress(self.root, self.plan, self.config)
            self.assertTrue(progress.observe({'seed': 2, 'status': status, 'target': None,
                                             'replay_verified': False}))
            self.assertEqual(len(progress.wins), 1)
            self.assertEqual(progress.reason, 'requires_data_review')
        progress = S.Progress(self.root, self.plan, self.config)
        self.assertFalse(progress.observe({'seed': 2, 'status': 'death', 'target': 0.0,
                                          'replay_verified': True, 'terminal_state_verified': True}))
        self.assertEqual(len(progress.wins), 1)

    def test_seed_draw_excludes_all_historical_roles_and_its_own_reservations(self):
        for name, role, seed in [('training', 'train', 10000000), ('validation', 'validation', 10000001),
                                 ('testing', 'final_test', 10000002), ('acceptance', 'acceptance', 10000003),
                                 ('current', 'train', 10000004)]:
            S.H.write_json(self.root / name / 'seeds.json', {role: [seed]})
        with patch.object(S.H.A, 'read_seeds', return_value=[10000005]):
            used, held_out, _ = S.seed_inventory(self.root)
        self.assertEqual(used, set(range(10000000, 10000006)))
        self.assertEqual(held_out, {10000001, 10000002, 10000003, 10000005})
        with patch.object(S.secrets, 'randbelow', side_effect=[0, 1, 2, 3, 4, 5, 6, 6, 7]):
            self.assertEqual(S.draw_seeds(2, used), [10000006, 10000007])

    def test_real_portal_win_replays_but_tampered_terminal_or_shards_fail(self):
        run = S.H.read_json(REPO / 'tests/fixtures/heart-portal-101890269.json.gz')
        seed = run['seed']
        gc = S.R.replay(seed, run['prefix'], self.config)
        run['terminal_fingerprint'] = S.R.fingerprint(gc)
        groups = S.R.training_samples(run, self.config)
        trace, encoded = self.root / f'episodes/{seed}.json.gz', self.root / f'encoded/{seed}.json.gz'
        S.H.write_json(trace, run)
        S.H.write_json(encoded, groups)
        row = {key: value for key, value in run.items() if key not in ('prefix', 'samples', 'roots')}
        row.update(replay_verified=True, terminal_state_verified=True, decision_count=len(groups),
                   trace_sha256=S.C.sha(trace), encoded_sha256=S.C.sha(encoded))
        result = self.root / f'results/{seed}.json'
        S.H.write_json(result, row)
        receipt = S.verify_success(self.root, seed, self.config, replay=True)
        self.assertEqual(receipt['floor'], 55)
        self.assertEqual(receipt['replayed_terminal_fingerprint'], run['terminal_fingerprint'])
        broken = copy.deepcopy(run)
        broken['terminal_fingerprint'] = 'wrong terminal RNG'
        S.H.write_json(trace, broken)
        S.H.write_json(result, {**row, 'trace_sha256': S.C.sha(trace),
                              'terminal_fingerprint': broken['terminal_fingerprint']})
        with self.assertRaisesRegex(ValueError, 'terminal state or RNG'):
            S.verify_success(self.root, seed, self.config, replay=True)
        S.H.write_json(trace, run)
        S.H.write_json(result, {**row, 'trace_sha256': S.C.sha(trace)})
        S.H.write_json(encoded, [])
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            S.verify_success(self.root, seed, self.config)

    def test_worker_captures_original_terminal_state_and_replay_verifies_it(self):
        self.config.update(simulations=50)
        seed = 9012345
        S.C.worker({'seed': seed, 'directory': str(self.root),
                    'output': str(self.root / f'results/{seed}.json')}, self.config)
        row = S.H.read_json(self.root / f'results/{seed}.json')
        self.assertTrue(row['terminal_state_verified'])
        self.assertTrue(row['replay_verified'])
        run = S.H.read_json(self.root / f'episodes/{seed}.json.gz')
        self.assertEqual(row['terminal_fingerprint'], S.R.fingerprint(S.R.replay(seed, run['prefix'], self.config)))
        self.assertIsNotNone(row['target'])


if __name__ == '__main__':
    unittest.main()
