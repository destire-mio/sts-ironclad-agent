"""Behavioral checks for the retrospective cross-family gradient audit."""
import importlib.util
from pathlib import Path

import numpy as np


spec = importlib.util.spec_from_file_location('signal_audit', Path(__file__).parents[1]/'docs/experiments/e193-gradient-signal.py')
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


def test_conflicting_families_do_not_count_their_own_positive_self_dot():
    summary, families, _ = D.alignment([[1., 0.], [-1., 0.], [0., 0.]])
    assert summary['counts'] == dict(positive=0, negative=2, numerically_zero=0, zero_gradient=1)
    assert [row['cosine'] for row in families[:2]] == [-1., -1.]
    assert summary['aggregate_energy_over_self_energy'] == 0.
    aligned, _, _ = D.alignment([[1., 0.], [2., 0.]])
    assert aligned['counts']['positive'] == 2


def test_manual_derivative_matches_autograd_with_residual_temperature_and_advantage():
    initial = {'0.weight': np.array([[.2, -.1], [-.3, .4]]),
               '0.bias': np.array([.1, .2]), '2.weight': np.array([[.3, -.7]]), '2.bias': np.array([.1])}
    state = {key: value.copy() for key, value in initial.items()}
    state['0.weight'][0, 0] += .04
    state['2.weight'][0, 1] -= .06
    values = np.array([[1., 0.], [0., 2.], [1., 1.]])
    base = np.array([.5, -.2, .1])
    _, current = D.forward(state, values)
    _, original = D.forward(initial, values)
    logits = (base + current - original)/.7
    weights = np.exp(logits-logits.max())
    row = dict(features=[[[i, float(v)] for i, v in enumerate(x) if v] for x in values],
               base_scores=base.tolist(), active=[1, 3, 4], chosen=3, chosen_active=1,
               probabilities=(weights/weights.sum()).tolist(), advantage=-2/3)
    manual, error = D.manual_gradient(state, initial, [row], .7)
    independent = D.autograd_gradient(state, initial, [row], .7)
    np.testing.assert_allclose(manual, independent, atol=1e-13, rtol=0)
    assert error == 0.
    opposite = dict(row, advantage=2/3)
    cancel, _ = D.manual_gradient(state, initial, [row, opposite], .7)
    np.testing.assert_allclose(cancel, 0., atol=1e-13, rtol=0)


def test_shared_action_offset_has_no_policy_gradient():
    state = {'0.weight': np.array([[.2, .3]]), '0.bias': np.array([.1]),
             '2.weight': np.array([[.4]]), '2.bias': np.array([.2])}
    row = dict(features=[[[0, 1.]], [[0, 1.]]], base_scores=[0., 0.], active=[0, 1],
               chosen=1, chosen_active=1, probabilities=[.5, .5], advantage=1.)
    gradient, _ = D.manual_gradient(state, state, [row], 1.)
    np.testing.assert_array_equal(gradient, np.zeros_like(gradient))
