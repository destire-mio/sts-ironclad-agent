import importlib.util
from itertools import product
from pathlib import Path

import numpy as np
import pytest


SPEC = importlib.util.spec_from_file_location('variance', Path(__file__).parents[1]/'docs/experiments/research-baseline-variance.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def exact_moments(p, baseline):
    values, means, weights = [], [], []
    for actions in product((0, 1), repeat=4):
        a = np.asarray(actions, dtype=float)
        scores = (a-p)[:, None]
        row, loo, state = M.estimate(scores, baseline*scores, a)
        values.append([row['loo_trace_variance'], row['state_trace_variance']])
        means.append([loo.item(), state.item()])
        weights.append(np.prod(np.where(a, p, 1-p)))
    values, means, weights = map(np.asarray, (values, means, weights))
    expected = weights @ means
    actual_variance = weights @ np.square(means-expected)
    assert weights @ values == pytest.approx(actual_variance, abs=1e-14)
    assert expected == pytest.approx([p*(1-p)]*2, abs=1e-14)
    return actual_variance


def test_four_rollout_estimators_match_exact_distribution_means_and_variances():
    for p in (.1, .4, .8):
        for baseline in (0., p, 1-p, 1.):
            exact_moments(p, baseline)


def test_better_return_prediction_can_increase_gradient_variance():
    p = .1
    optimal = exact_moments(p, 1-p)
    value_predictor = exact_moments(p, p)
    assert value_predictor[1] > optimal[1] + .01
    assert p*(1-p) < p*(1-(1-p))**2+(1-p)*(1-p)**2


def test_unbiased_estimate_keeps_negative_values_and_zero_reward_groups():
    found_negative = False
    for rewards in product((0., 1.), repeat=4):
        row, _, _ = M.estimate([[3.], [-2.], [5.], [-7.]], [[1.], [2.], [3.], [4.]], rewards)
        found_negative |= row['loo_trace_variance'] < 0
    assert found_negative
    row, _, _ = M.estimate([[3.], [-2.], [5.], [-7.]], [[1.], [2.], [3.], [4.]], [0.]*4)
    assert row['loo_trace_variance'] == 0 and row['state_trace_variance'] > 0


def test_multi_parameter_episode_statistics_match_independent_exact_enumeration():
    probabilities = np.array([.2, .3, .5])
    scores = np.array([[1., -3.], [2., 1.], [-1.6, .6]])
    assert probabilities @ scores == pytest.approx([0, 0])
    estimates, gradients, weights = [], [], []
    for selected in product(range(3), repeat=4):
        s = scores[list(selected)]; r = (np.asarray(selected) == 0).astype(float)
        row, loo, state = M.estimate(s, .3*s, r)
        estimates.append([row['loo_trace_variance'], row['state_trace_variance']])
        gradients.append([loo, state]); weights.append(np.prod(probabilities[list(selected)]))
    g = np.asarray(gradients); w = np.asarray(weights)
    mean = np.einsum('n,nkd->kd', w, g)
    actual = np.einsum('n,nkd->k', w, np.square(g-mean))
    assert w @ estimates == pytest.approx(actual)
