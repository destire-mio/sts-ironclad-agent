from pathlib import Path
import sys
from types import SimpleNamespace as S

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_paired_afterstate_value as A


def test_fixed_continuation_win_pair_pushes_alternative_up_and_parent_down():
    logits = torch.zeros(3, requires_grad=True)
    labels = torch.tensor([1., 0., 0.])
    loss = A.paired_loss(logits, labels, 0.)
    loss.backward()
    assert logits.grad[0] < 0 and logits.grad[1] > 0 and logits.grad[2] == 0
    changed = logits.detach()-0.1*logits.grad
    assert A.paired_loss(changed, labels, 0.) < loss
    assert A.select(changed[:2].sigmoid().numpy(), 1) == 0


def test_swapping_pair_keeps_loss_and_identical_states_have_zero_difference_gradient():
    values = torch.tensor([.2, -.9, .4])
    labels = torch.tensor([1., 0., 1.])
    assert torch.equal(A.paired_loss(values, labels, 1.),
                       A.paired_loss(values[[1, 0, 2]], labels[[1, 0, 2]], 1.))
    tied = torch.tensor([.7, .7, .4], requires_grad=True)
    A.paired_loss(tied, torch.ones(3), 0.).backward()
    assert torch.equal(tied.grad, torch.zeros(3))


def test_absolute_calibration_preserves_success_probability_direction():
    values = torch.zeros(3, requires_grad=True)
    A.paired_loss(values, torch.tensor([0., 0., 1.]), 1.).backward()
    assert values.grad[0] == values.grad[1] == 0 and values.grad[2] < 0


def test_no_support_or_tied_prediction_keeps_parent_without_reading_outcome():
    assert A.select([.7, .7, .7], 2) == 2
    assert A.select([.5, .5000005], 0) == 0
    assert A.select([.5, .51], 0) == 1
    assert A.select([.1, .99], 0, enabled=False) == 0
    with pytest.raises(ValueError, match='scores'):
        A.select([.1, float('nan')], 0)


def test_actual_successor_ownership_rejects_forged_pair_family():
    data = A.Data.__new__(A.Data)
    data.rows = [dict(seed=11, successors=[0, 2], parent=0)]
    data.pairs = np.array([[0, 1]])
    data.value = A.V.Data.__new__(A.V.Data)
    data.value.targets = np.zeros(4, dtype=np.float32)
    data.value.ends = np.array([2, 4]); data.value.seeds = np.array([11, 22])
    with pytest.raises(ValueError, match='held family'):
        data.batch(np.array([0]), np.array([0]), {11})


def test_pair_sampling_weights_families_then_menus_and_uses_same_family_calibration():
    data = A.Data.__new__(A.Data)
    data.by_seed = {11: [0], 22: [1, 2]}
    data.rows = [dict(pair_begin=0, pair_end=3), dict(pair_begin=3, pair_end=5), dict(pair_begin=5, pair_end=9)]
    families = [dict(seed=11, begin=0, end=2), dict(seed=22, begin=2, end=12)]
    pairs, calibration = data.sample(families, np.array([[0., .9, .9, .9], [.5, 0., .9, .9], [.99, .99, .99, 0.]]))
    np.testing.assert_array_equal(pairs, [2, 4, 8])
    np.testing.assert_array_equal(calibration, [1, 11, 2])


def test_many_descendants_do_not_outweigh_one_other_seed_family():
    gain = dict(seed=11, parent=0, chosen=1, labels=[0, 1])
    loss = dict(seed=22, parent=0, chosen=1, labels=[1, 0])
    summary = A.summarize([gain]*20+[loss])
    assert summary['gained'] == 20 and summary['lost'] == 1
    assert summary['family_mean_gain'] == 0
