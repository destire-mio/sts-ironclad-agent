"""The learned greedy execution rule must not become the parent-control flag."""
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'agent'))
import heart_greedy_policy_evaluation as L


def test_learned_greedy_action_can_override_parent_without_sampling():
    policy = object.__new__(L.Policy)
    policy.net = torch.nn.Linear(2, 1, bias=False).double()
    policy.initial = torch.nn.Linear(2, 1, bias=False).double().requires_grad_(False)
    with torch.no_grad():
        policy.net.weight[:] = torch.tensor([[-1., 1.]])
        policy.initial.weight.zero_()
    policy.samples = []
    policy.x = SimpleNamespace(R=SimpleNamespace(kind=lambda d: d[0]))
    policy.rng = SimpleNamespace(random=lambda: pytest.fail('greedy execution consumed a policy random draw'))
    policy.menu = lambda *args: (torch.eye(2, dtype=torch.float64), np.array([.5, 0.]), np.array([0, 1]), 0, np.array([.6, .4]))
    assert policy.choose(None, None, [None, None], [[3], [3]]) == 1
    assert policy.samples[-1]['parent'] == 0 and policy.samples[-1]['chosen'] == 1
    with torch.no_grad():
        policy.net.weight.zero_()
    assert policy.choose(None, None, [None, None], [[3], [3]]) == 0


def test_original_parent_ties_and_finite_support_are_preserved():
    assert L.greedy_position([1., 1.], [2, 7], 7) == 1
    assert L.greedy_position([1., 1.-5e-10], [2, 7], 7) == 1
    assert L.greedy_position([1., 1.-2e-9], [2, 7], 7) == 0
    for scores, active, parent in [([1., np.nan], [0, 1], 0), ([1., 2.], [0, 0], 0), ([1.], [0], 2)]:
        with pytest.raises(ValueError):
            L.greedy_position(scores, active, parent)
