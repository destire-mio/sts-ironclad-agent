import importlib.util
from pathlib import Path

import numpy as np


spec = importlib.util.spec_from_file_location('state_baseline', Path(__file__).parents[1]/'agent/heart_state_baseline.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


def test_baseline_uses_whole_public_menu_not_sampled_action_or_result():
    rng = np.random.default_rng(195)
    state = {'0.weight': rng.normal(size=(192, 5529)), '0.bias': rng.normal(size=192)}
    scalars = np.arange(12)/10
    rows = []
    for kind in (0, 7, 18):
        row = [(kind, 1.)]+[(807+12*kind+i, float(v)) for i, v in enumerate(scalars) if v]
        rows.append(row)
    record = dict(active=[0, 1, 2], features=rows, probabilities=[.2, .3, .5], chosen_active=0, reward=0)
    value = B.state_features([record], state)
    changed = dict(record, chosen_active=2, reward=1)
    np.testing.assert_array_equal(value, B.state_features([changed], state))
    order = [2, 0, 1]
    reordered = dict(record, active=[record['active'][i] for i in order],
                     features=[rows[i] for i in order], probabilities=[record['probabilities'][i] for i in order])
    np.testing.assert_allclose(value, B.state_features([reordered], state), atol=1e-14, rtol=0)
    np.testing.assert_array_equal(value[0, 192:], scalars)
    shifted = dict(record, features=[list(row)+[(3000, 2.)] for row in rows])
    assert not np.allclose(value, B.state_features([shifted], state))


def test_weighted_fit_matches_augmented_least_squares_and_constant_columns():
    rng = np.random.default_rng(17)
    x = rng.normal(size=(100, 9)); x[:, -1] = 1.
    y = (x[:, 0]+.5*x[:, 1] > .2).astype(float)
    w = rng.uniform(.1, 2., len(x))
    model = B.fit_ridge(x, y, w)
    z = (x-model['mean'])/model['scale']; normalized = w/w.sum()
    a = np.r_[z*np.sqrt(normalized[:, None]), np.sqrt(B.RECIPE['ridge'])*np.eye(x.shape[1])]
    b = np.r_[(y-model['intercept'])*np.sqrt(normalized), np.zeros(x.shape[1])]
    expected = np.linalg.lstsq(a, b, rcond=None)[0]
    np.testing.assert_allclose(model['coefficient'], expected, atol=1e-12, rtol=0)
    assert abs(model['coefficient'][-1]) < 1e-12
    predictions = B.predict(model, x)
    assert ((predictions >= 0) & (predictions <= 1)).all()
    assert B.error(y, predictions, w) < B.error(y, np.full(len(y), model['intercept']), w)


def test_family_split_and_episode_weights_prevent_row_count_reweighting():
    assert len({B.family_fold(seed) for seed in range(128)}) == 3
    labels = np.r_[np.zeros(2), np.ones(18)]
    weights = np.r_[np.full(2, .25/2), np.full(18, .25/18)]
    model = B.fit_ridge(np.zeros((20, 2)), labels, weights)
    assert model['intercept'] == .5
    np.testing.assert_array_equal(B.predict(model, np.ones((3, 2))), [.5]*3)
    assert B.family_fold(1000) == B.family_fold(1000)
