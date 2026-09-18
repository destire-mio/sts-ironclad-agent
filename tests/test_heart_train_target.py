"""The 10% target means complete natural Heart runs on the whole fixed train pool."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
os.environ.setdefault('STS_LIGHTSPEED_BUILD', str(REPO.parent / 'ironclad-alignment/build'))
import heart_train_target as T


class TrainingTargetTest(unittest.TestCase):
    def outcomes(self, total, wins):
        return [{'seed': i, 'status': 'heart_win' if i < wins else 'death', 'floor': 57 if i < wins else 8,
                 'replay_verified': True, 'terminal_state_verified': True,
                 'win_policy_verified': i < wins, 'checkpoint_sha256': 'frozen'}
                for i in range(total)]

    def test_exact_whole_pool_threshold_requires_1154_of_11536(self):
        seeds = list(range(11536))
        below = T.summarize_target(self.outcomes(11536, 1153), seeds, seeds, 'full', 'frozen')
        above = T.summarize_target(self.outcomes(11536, 1154), seeds, seeds, 'full', 'frozen')
        self.assertFalse(below['full_training_target_reached'])
        self.assertTrue(above['full_training_target_reached'])
        self.assertEqual(above['heart_wins_required'], 1154)

    def test_successful_probe_cannot_claim_complete_training_target(self):
        report = T.summarize_target(self.outcomes(10, 10), list(range(10)), list(range(100)), 'probe', 'frozen')
        self.assertTrue(report['probe_threshold_reached'])
        self.assertFalse(report['full_training_target_reached'])
        with self.assertRaisesRegex(ValueError, 'omitted'):
            T.summarize_target(self.outcomes(10, 10), list(range(10)), list(range(100)), 'full', 'frozen')

    def test_missing_games_faults_mixed_models_and_unverified_wins_block_target(self):
        seeds = list(range(10))
        for kind in ('missing', 'fault', 'different_model', 'unverified_win', 'unverified_terminal'):
            runs = self.outcomes(10, 2)
            if kind == 'missing':
                runs.pop()
            elif kind == 'fault':
                runs[-1]['status'] = 'timeout'
            elif kind == 'different_model':
                runs[-1]['checkpoint_sha256'] = 'changed'
            elif kind == 'unverified_win':
                runs[0]['win_policy_verified'] = False
            else:
                runs[0]['terminal_state_verified'] = False
            with self.subTest(kind=kind):
                report = T.summarize_target(runs, seeds, seeds, 'full', 'frozen')
                self.assertFalse(report['full_training_target_reached'])
                self.assertFalse(report['complete'])
                self.assertIsNone(report['training_heart_rate'])

    def test_duplicate_or_foreign_seed_cannot_inflate_rate(self):
        runs = self.outcomes(10, 1)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            T.summarize_target(runs + [runs[0]], list(range(10)), list(range(10)), 'full', 'frozen')
        with self.assertRaisesRegex(ValueError, 'non-training'):
            T.summarize_target(runs, list(range(10)), list(range(9)), 'probe', 'frozen')

    def test_real_frozen_model_runs_replay_and_wrong_checkpoint_is_not_a_death(self):
        T.H.torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            net = T.S.G.GuidedScorer((8, 8), 3.0)
            model = root / 'model.pt'
            T.H.torch.save({'model_type': net.model_type, 'arch': [8, 8], 'prior_strength': 3.0,
                            'state_dict': net.state_dict()}, model)
            config = {**T.H.read_json(REPO / 'configs/heart_round1.json'), 'simulations': 10, 'workers': 2}
            jobs = [{'seed': seed, 'mode': 'evaluate', 'directory': str(root), 'checkpoint': str(model),
                     'checkpoint_sha256': T.S.sha(model), 'output': str(root / f'results/{seed}.json')}
                    for seed in (9012345, 9012346)]
            runs = T.H.run_jobs(root, jobs, config, 'test_target', time.monotonic() + 60, worker_fn=T.worker)
            report = T.summarize_target(runs, [9012345, 9012346], [9012345, 9012346], 'full', T.S.sha(model))
            self.assertTrue(report['complete'], runs)
            for run in runs:
                trace = T.H.read_json(root / f"episodes/{run['seed']}.json.gz")
                encoded = T.H.read_json(root / f"encoded/{run['seed']}.json.gz")
                self.assertTrue(trace['prefix'])
                self.assertEqual(len(encoded), run['decision_count'])
                self.assertTrue(run['replay_verified'])
                self.assertTrue(run['terminal_state_verified'])
                with self.assertRaisesRegex(ValueError, 'terminal state or RNG changed'):
                    T.R.training_samples({**trace, 'terminal_fingerprint': 'different_final_rng'}, config)
            if trace['status'] != 'heart_win':
                loaded = T.H.load_scorer(T.H.torch.load(model, weights_only=True))
                with self.assertRaisesRegex(ValueError, 'did not reproduce'):
                    T.verify_policy_win({**trace, 'status': 'heart_win'}, loaded, config)
            invalid = [{**jobs[0], 'checkpoint_sha256': 'changed', 'output': str(root / 'invalid.json')}]
            result = T.H.run_jobs(root, invalid, config, 'test_changed_model', time.monotonic() + 60, worker_fn=T.worker)[0]
            self.assertEqual(result['status'], 'evaluation_error')
            self.assertIsNone(result['target'])


if __name__ == '__main__':
    unittest.main()
