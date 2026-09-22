from pathlib import Path
import sys

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_item_transfer as R


def layout():
    return dict(chosen=30, card_begin=24, cards=2, upgrade=26, misc=27, relic_begin=28,
                relics=2, card_actions=[3, 11], relic_actions=[16, 9, 12],
                counts=[[0, 1], [2, 3]], upgrade_sums=[4, 5], misc_sums=[6, 7], presence=[8, 9])


def test_upgraded_item_uses_owned_embedding_without_changing_source_or_parent():
    features = torch.zeros((1, 100)); features[0, [33, 55]] = 1.
    features[0, 56] = .004; features[0, 57] = .050; features[0, 3] = .1
    features[0, 70] = .75
    original = features.clone()
    result = R.route_items(features, layout()).to_dense()
    assert torch.equal(features, original)
    assert float(result[0, 55]) == 0 and float(result[0, 2]) == 0
    torch.testing.assert_close(result[0, [3, 5, 7, 70]], torch.tensor([.15, .004, .05, .75]))
    np.testing.assert_allclose(result.numpy(), R.numpy_route(features.numpy(), layout()), atol=1e-7)
    weights = torch.zeros(100, requires_grad=True)
    (result @ weights).sum().backward()
    assert weights.grad[3] > 0 and weights.grad[55] == 0


def test_relic_reuses_presence_but_map_skip_and_remove_keep_their_input():
    features = torch.zeros((4, 100))
    features[0, [46, 59]] = 1.  # Boss relic
    features[1, [30, 59]] = 1.  # Map; deliberately populated identity is inert
    features[2, [47, 59]] = 1.  # Boss skip
    features[3, [44, 54]] = 1.  # Shop remove, not an acquisition token
    result = R.route_items(features, layout()).to_dense()
    assert result[0, 9] == 1 and result[0, 59] == 0
    assert torch.equal(result[1:], features[1:])
    np.testing.assert_array_equal(result.numpy(), R.numpy_route(features.numpy(), layout()))


def test_sparse_and_dense_route_agree_with_numpy_for_existing_inventory():
    rng = np.random.default_rng(88)
    features = np.zeros((12, 100), dtype=np.float32)
    features[:, :10] = rng.random((12, 10))
    for i in range(12):
        features[i, 30+([3, 16, 0][i % 3])] = 1
        features[i, 54+i % 2] = 1
        features[i, 58+i % 2] = 1
        features[i, 56] = (i % 2)/1000
    t = torch.tensor(features)
    expected = R.numpy_route(features, layout())
    np.testing.assert_allclose(R.route_items(t, layout()).to_dense().numpy(), expected, atol=1e-7)
    np.testing.assert_allclose(R.route_items(t.to_sparse(), layout()).to_dense().numpy(), expected, atol=1e-7)
