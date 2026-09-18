"""Exercise result isolation, recycling and real replay in the collection pool."""
import copy
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
import heart_bulk_collect as C
import heart_runtime as R


def fixture_worker(job, config):
    output = Path(job['output'])
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = job.get('test_mode')
    if mode == 'crash':
        os._exit(17)
    if mode == 'hang':
        time.sleep(60)
    if mode == 'missing':
        return
    C.H.write_json(output, {'seed': job['seed'], 'status': 'death', 'target': 0.0,
                           'pid': os.getpid(), 'value': job['value']})
    if mode == 'commit_then_crash':
        os._exit(19)


class CollectionPoolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = {'workers': 1, 'prefix_timeout': 10, 'collection_games_per_worker': 2}

    def tearDown(self):
        self.temp.cleanup()

    def jobs(self, modes):
        return [{'seed': i + 1, 'test_mode': mode, 'value': ['input', i],
                 'output': str(self.root / f'{i + 1}.json')}
                for i, mode in enumerate(modes)]

    def run_jobs(self, jobs, deadline=None, worker_fn=fixture_worker):
        result = C.run_collection_jobs(self.root, jobs, self.config,
            time.monotonic() + 60 if deadline is None else deadline, worker_fn)
        self.assertEqual(mp.active_children(), [], 'pool left running children')
        return result

    def test_reuse_recycle_and_resume_preserve_committed_outputs(self):
        jobs = self.jobs(['ok'] * 5)
        rows = self.run_jobs(jobs)
        self.assertEqual([r['value'] for r in rows], [j['value'] for j in jobs])
        self.assertEqual(rows[0]['pid'], rows[1]['pid'])
        self.assertNotEqual(rows[1]['pid'], rows[2]['pid'])
        self.assertEqual(rows[2]['pid'], rows[3]['pid'])
        before = [Path(j['output']).read_bytes() for j in jobs]
        self.run_jobs(jobs)
        self.assertEqual(before, [Path(j['output']).read_bytes() for j in jobs])

    def test_crash_and_missing_output_do_not_label_other_jobs(self):
        self.config.update(workers=2, collection_games_per_worker=32)
        rows = self.run_jobs(self.jobs(['crash', 'ok', 'missing', 'ok', 'commit_then_crash', 'ok']))
        for i in (0, 2):
            self.assertEqual(rows[i]['status'], 'process_error')
            self.assertIsNone(rows[i]['target'])
        for i in (1, 3, 4, 5):
            self.assertEqual(rows[i]['status'], 'death')
            self.assertEqual(rows[i]['value'], ['input', i])

    def test_timeout_kills_one_job_then_continues(self):
        self.config.update(prefix_timeout=5, collection_games_per_worker=32)
        rows = self.run_jobs(self.jobs(['ok', 'hang', 'ok']))
        self.assertEqual([r['status'] for r in rows], ['death', 'timeout', 'death'])
        self.assertIsNone(rows[1]['target'])
        self.assertNotEqual(rows[0]['pid'], rows[2]['pid'])

    def test_expired_deadline_does_not_start_or_label_pending_jobs(self):
        jobs = self.jobs(['ok', 'ok'])
        self.assertEqual(self.run_jobs(jobs, time.monotonic() - 1), [])
        self.assertFalse(any(Path(j['output']).exists() for j in jobs))

    def test_target_stops_new_jobs_and_preserves_active_results_and_resume(self):
        self.config.update(workers=2, collection_games_per_worker=32)
        jobs = self.jobs(['ok'] * 12)
        observed = []
        def target(row):
            observed.append(row['seed'])
            return len(observed) >= 1
        rows = C.run_collection_jobs(self.root, jobs, self.config,
            time.monotonic() + 60, fixture_worker, on_result=target)
        self.assertEqual(len(rows), 2, 'only the two in-flight games should finish')
        self.assertEqual({row['seed'] for row in rows}, {1, 2})
        self.assertTrue(all(row['status'] == 'death' for row in rows))
        self.assertEqual(mp.active_children(), [])
        before = [Path(job['output']).read_bytes() for job in jobs[:2]]
        resumed = C.run_collection_jobs(self.root, jobs, self.config,
            time.monotonic() + 60, fixture_worker, on_result=lambda row: True)
        self.assertEqual(len(resumed), 2, 'a reached target must not start jobs on resume')
        self.assertEqual(before, [Path(job['output']).read_bytes() for job in jobs[:2]])
        self.assertFalse(any(Path(job['output']).exists() for job in jobs[2:]))

    def test_frozen_collector_uses_matching_current_code_and_selected_engine(self):
        parent, frozen = self.root / 'parent', self.root / 'frozen'
        (parent / 'engine').mkdir(parents=True)
        (parent / 'engine/slaythespire-stale.so').write_bytes(b'old engine')
        (parent / 'engine/alignment-manifest.json').write_text('{"scope":"IRONCLAD"}')
        frozen.mkdir()
        origin = C.freeze_runtime(parent, frozen)
        module = Path(C.H.A.sts.__file__)
        self.assertEqual(list((frozen / 'engine').glob('slaythespire*.so')),
                         [frozen / 'engine' / module.name])
        self.assertEqual((frozen / 'engine' / module.name).read_bytes(), module.read_bytes())
        self.assertEqual(origin['engine'], str(module.resolve()))
        for name in ('heart_runtime.py', 'heart_bulk_collect.py', 'armG_train.py', 'heart_train.py', 'heart_guided.py'):
            self.assertEqual((frozen / 'source' / name).read_bytes(), (REPO / 'agent' / name).read_bytes())
        invalid = self.root / 'invalid'
        invalid.mkdir()
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            C.freeze_runtime(parent, invalid, self.root / 'missing-engine')
        self.assertFalse((invalid / 'engine').exists())

    def test_deadline_stops_active_job_without_labelling_pending_job(self):
        jobs = self.jobs(['hang', 'ok'])
        rows = self.run_jobs(jobs, time.monotonic() + 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'timeout')
        self.assertIsNone(rows[0]['target'])
        self.assertFalse(Path(jobs[1]['output']).exists())

    def test_trace_only_recording_retains_actions_rng_and_training_features(self):
        config = json.loads((REPO / 'configs/heart_round1.json').read_text())
        config.update(simulations=50, root_min_floor=1, roots_per_seed=3)
        full = R.rollout(9012345, config, net=C.T.RoleTeacher(1), record=True)
        compact = R.rollout(9012345, config, net=C.T.RoleTeacher(1), record=True,
                            record_samples=False)
        self.assertIsNotNone(full['target'])
        self.assertTrue(full['samples'])
        excluded = {'samples', 'roots', 'seconds'}
        self.assertEqual({k: v for k, v in full.items() if k not in excluded},
                         {k: v for k, v in compact.items() if k not in excluded})
        self.assertEqual(compact['samples'], [])
        self.assertEqual(compact['roots'], [])
        self.assertEqual(R.training_samples(full, config), R.training_samples(compact, config))
        self.assertEqual(R.fingerprint(R.replay(full['seed'], full['prefix'], config)),
                         R.fingerprint(R.replay(compact['seed'], compact['prefix'], config)))
        broken = copy.deepcopy(compact)
        broken['prefix'][0]['before'] = 'corrupted RNG/state'
        with self.assertRaisesRegex(RuntimeError, 'prefix pre-state'):
            R.training_samples(broken, config)


if __name__ == '__main__':
    unittest.main()
