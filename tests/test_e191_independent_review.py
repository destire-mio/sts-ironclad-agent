"""Check the separate optimizer reviewer before reading experiment outcomes."""
import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'agent'))
import heart_whole_policy_gradient as G

spec = importlib.util.spec_from_file_location('e191_independent_review', ROOT/'docs/experiments/e191-review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_independent_optimizer_reconstructs_grouped_terminal_update():
    torch.manual_seed(191)
    initial = torch.nn.Sequential(torch.nn.Linear(2, 3), torch.nn.ReLU(), torch.nn.Linear(3, 1)).double()
    policy = SimpleNamespace(initial=copy.deepcopy(initial).requires_grad_(False), net=copy.deepcopy(initial), temperature=1.25)
    independently_updated = copy.deepcopy(initial)
    rows, records = [], []
    choices = [(0, 0), (0, 1), (1, 0), (1, 1)]
    for seed in range(128):
        for rep, path in enumerate(choices):
            samples = [dict(active=[0, 1], chosen_active=choice, base_scores=[0., 0.],
                            probabilities=[.5, .5], log_probability=float(np.log(.5)),
                            features=[[[0, 1.]], [[1, 1.]]]) for choice in path]
            rows.append(dict(seed=seed, policy_sampling_seed=rep, checkpoint_sha256='fixture',
                             status='heart_win' if rep == 3 else 'death', policy_samples=samples,
                             audit=dict(public_inputs_sampling_state_rng_and_terminal_verified=True)))
            records.extend(dict(sample, advantage=1. if rep == 3 else -1/3) for sample in samples)
    original = G.fit(policy, rows, 0, list(range(128)), 'fixture')
    reconstructed = review.replay_update(independently_updated, copy.deepcopy(initial).requires_grad_(False),
                                        records, G.RECIPE, 0, 1.25)
    assert original['updated'] and original['optimizer_updates'] == reconstructed['optimizer_updates'] == 16
    for name, tensor in policy.net.state_dict().items():
        torch.testing.assert_close(independently_updated.state_dict()[name], tensor, rtol=0, atol=1e-10)
    assert any(not torch.equal(initial.state_dict()[name], tensor) for name, tensor in policy.net.state_dict().items())
    for a, b in zip(original['curve'], reconstructed['curve'], strict=True):
        assert abs(a['policy_loss']-b['policy_loss']) < 1e-12
        assert abs(a['kl']-b['kl']) < 1e-12


def test_sparse_duplicate_columns_are_rejected():
    row = dict(active=[0], base_scores=[0.], probabilities=[1.], features=[[[0, 1.], [0, 2.]]])
    with pytest.raises(AssertionError):
        review.materialize([row], 2)


def test_paired_counts_do_not_turn_equal_win_rates_into_a_gain():
    result = review.paired([1, 0, 1, 0], [0, 1, 1, 0])
    assert result['baseline_wins'] == result['candidate_wins'] == 2
    assert result['paired'] == dict(baseline_only=1, candidate_only=1, both_win=1, both_fail=1)
    assert result['net_gain'] == 0 and result['exact_p'] == 1.
    assert review.paired([0]*8, [1]*8)['exact_p'] == 2/256
