from pathlib import Path
import sys
from types import SimpleNamespace as S

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_parent_state_value as V


def test_prediction_input_ignores_menu_and_excluded_observation():
    raw = torch.tensor([[.2, .7, .5, 1., 0., .9], [.2, .1, .5, 0., 1., .3]])
    store = S(spec=dict(width=6, descriptor_dim=2), shared=S(take=lambda ids: raw[ids].to_sparse()))
    values = V.state_features(store, np.array([0, 1]), [0, 2]).to_dense()
    assert torch.equal(values[0], values[1])
    assert values.shape == (2, 8) and values[0, 0] == .2
    assert raw[0, 1] == .7


def test_fit_baseline_weights_families_equally_and_falls_back_without_held_labels():
    data = V.Data.__new__(V.Data)
    data.cells = np.array([0, 0, 0, 0, 0], dtype=np.uint8)
    data.targets = np.array([1, 0, 0, 0, 1], dtype=np.float32)
    families = [dict(begin=0, end=1), dict(begin=1, end=4)]
    table = data.baseline(families)
    np.testing.assert_array_equal(table, np.full(256, .5))
    data.targets[4] = 0
    np.testing.assert_array_equal(table, data.baseline(families))


def test_boundary_row_belongs_to_next_family_and_cannot_be_labeled_by_fit_role():
    data = V.Data.__new__(V.Data)
    data.targets = np.zeros(5, dtype=np.float32)
    data.ends, data.seeds = np.array([2, 5]), np.array([11, 22])
    with pytest.raises(ValueError, match='held family'):
        data.batch(np.array([2]), {11})


def test_baseline_buckets_match_public_resource_boundaries():
    scalars = np.array([[.5, .5, .25, 0., .15], [.5, .5, .25, 0., .16],
                       [.125, .5, .5, 4/15, .26], [0., .5, 1., 16/15, .36]], dtype=np.float32)
    np.testing.assert_array_equal(V.baseline_cells(scalars), [12, 13, 86, 243])
