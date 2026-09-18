"""Check the gate's observable actions and deterministic natural-run controls."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
import heart_floor_gate as F


class FloorGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        F.H.torch.set_num_threads(1)
        cls.source = REPO / 'runs/heart-branch-training-20260916-01'
        cls.models = {arm: {'path': str(cls.source / filename), 'sha256': F.S.sha(cls.source / filename)}
            for arm, filename in [('baseline', 'model.pt'), ('candidate', 'candidate.pt')]}
        cls.config = F.H.read_json(cls.source / 'config.json')

    def test_floor_32_uses_old_actions_and_floor_33_uses_new_actions(self):
        class Fixed:
            def __init__(self, choice): self.choice = choice
            def choose(self, gc, observation, actions, descriptions): return self.choice
        policy = F.FloorPolicy(Fixed(0), Fixed(1), 33)
        gc = SimpleNamespace(floor_num=0, act=1, screen_state='map')
        actions = [SimpleNamespace(bits=41), SimpleNamespace(bits=82)]
        with patch.object(F.R, 'fingerprint', return_value='state'):
            for floor, expected in [(0, 41), (32, 41), (33, 82), (34, 82)]:
                gc.floor_num = floor
                chosen = policy.choose(gc, [1.0], actions, [[1.0], [2.0]])
                self.assertEqual(actions[chosen].bits, expected)
                self.assertEqual(policy.choices[-1]['action'], expected)

    def fixture(self):
        first = {'kind': 'outside', 'before': 'early', 'action': 11}
        battle = {'kind': 'battle', 'before': 'battle', 'actions': [7]}
        last = {'kind': 'outside', 'before': 'takeover', 'action': 22}
        baseline = {'prefix': [first, battle, last], 'status': 'death', 'act': 3, 'floor': 33,
                    'hp': 0, 'keys': [True] * 3, 'terminal_fingerprint': 'old-end'}
        row = copy.deepcopy(baseline)
        row['prefix'][2]['action'] = 33
        row['terminal_fingerprint'] = 'new-end'
        row['choices'] = [dict(floor=32, act=2, screen='rest', before='early', action=11, arm='baseline'),
                          dict(floor=33, act=3, screen='map', before='takeover', action=33, arm='candidate')]
        candidate = copy.deepcopy(row)
        return row, baseline, candidate

    def test_accepts_only_post_gate_disagreement_with_same_initial_state(self):
        row, baseline, candidate = self.fixture()
        audit = F.audit_gate(row, baseline, candidate, 33)
        self.assertTrue(audit['verified'])
        self.assertTrue(audit['same_candidate_takeover_control'])
        self.assertEqual(audit['first_baseline_disagreement']['prefix_index'], 2)

    def test_pre_gate_combat_and_takeover_rng_drift_are_rejected(self):
        for where in ('combat', 'takeover'):
            row, baseline, candidate = self.fixture()
            if where == 'combat': row['prefix'][1]['actions'] = [8]
            else:
                row['prefix'][2]['before'] = 'wrong-rng'
                row['choices'][1]['before'] = 'wrong-rng'
            with self.assertRaisesRegex(ValueError, 'drift before'):
                F.audit_gate(row, baseline, candidate, 33)

    def test_choice_log_cannot_claim_candidate_before_gate(self):
        row, baseline, candidate = self.fixture()
        row['choices'][0]['arm'] = 'candidate'
        with self.assertRaisesRegex(ValueError, 'floor gate'):
            F.audit_gate(row, baseline, candidate, 33)

    def test_no_takeover_requires_identical_baseline_terminal(self):
        row, baseline, candidate = self.fixture()
        row['prefix'] = copy.deepcopy(baseline['prefix'][:1])
        row['choices'] = row['choices'][:1]
        baseline['prefix'] = copy.deepcopy(row['prefix'])
        row['terminal_fingerprint'] = baseline['terminal_fingerprint']
        self.assertFalse(F.audit_gate(row, baseline, candidate, 33)['reached_gate'])
        row['terminal_fingerprint'] = 'corrupt'
        with self.assertRaisesRegex(ValueError, 'without candidate'):
            F.audit_gate(row, baseline, candidate, 33)

    def test_timeout_and_unverified_states_do_not_become_deaths(self):
        row, baseline, candidate = self.fixture()
        shas = {arm: info['sha256'] for arm, info in self.models.items()}
        row.update(seed=12, target=0.0, model_shas=shas, switch_floor=33,
            policy_sha256=F.policy_identity(shas, 33), replay_verified=True,
            terminal_state_verified=True, gate_audit=F.audit_gate(row, baseline, candidate, 33))
        self.assertTrue(F.valid_gated(row, 12, shas, 33))
        self.assertFalse(F.valid_gated({**row, 'status': 'timeout'}, 12, shas, 33))
        self.assertFalse(F.valid_gated({**row, 'switch_floor': 32}, 12, shas, 33))
        self.assertFalse(F.valid_gated({**row, 'replay_verified': False}, 12, shas, 33))

    def test_gate_extremes_reproduce_frozen_natural_policy_and_rng(self):
        # Both controls already exist in E08. This is not a preview of gate-33 outcomes.
        seed = 951621846
        for floor, arm in [(10**9, 'baseline'), (0, 'candidate')]:
            with self.subTest(arm=arm):
                actual = F.natural_episode(seed, self.models, self.config, floor)
                expected = F.H.read_json(self.source / f'evaluation/{arm}/{seed}.json.gz')
                self.assertEqual(actual['prefix'], expected['prefix'])
                self.assertEqual(F.P.terminal_signature(actual), F.P.terminal_signature(expected))
                self.assertTrue(actual['replay_verified'])
                self.assertTrue(all(choice['arm'] == arm for choice in actual['choices']))


if __name__ == '__main__':
    unittest.main()
