from pathlib import Path
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_card_combat_delta as D


def test_damage_and_survival_targets_keep_direction_without_rewarding_floor():
    values = torch.zeros((2, 2), requires_grad=True)
    outcomes = torch.tensor([[-.1, 1.], [-.8, 0.]])
    loss = (D.differences(values)-D.differences(outcomes)).square().mean()
    loss.backward()
    assert bool((values.grad[0] < 0).all()) and bool((values.grad[1] > 0).all())
    assert torch.equal(D.differences(outcomes[[1, 0]]), -D.differences(outcomes))
    same = torch.tensor([[.3, .9], [.3, .9]])
    assert torch.equal(D.differences(same), torch.zeros((1, 2)))


def test_missing_outcome_is_rejected_before_target_indexing():
    data = D.Data.__new__(D.Data)
    data.rows = [dict(successors=[0, 1], parent=0)]
    data.pairs = np.array([[0, 1]])
    data.first = np.array([0, -1])
    class PublicValue:
        def batch(self, ids, allowed): return torch.zeros((2, 1)), torch.zeros(2)
    data.value = PublicValue()
    with pytest.raises(ValueError, match='missing mapped-combat'):
        data.batch(np.array([0]), {11})


def test_held_state_cannot_reach_combat_labels_even_with_forged_row_metadata():
    data = D.Data.__new__(D.Data)
    data.rows = [dict(seed=11, successors=[0, 2], parent=0)]
    data.pairs = np.array([[0, 1]])
    data.value = D.V.Data.__new__(D.V.Data)
    data.value.targets = np.zeros(4, dtype=np.float32)
    data.value.ends = np.array([2, 4]); data.value.seeds = np.array([11, 22])
    with pytest.raises(ValueError, match='held family'):
        data.batch(np.array([0]), {11})


def test_sampler_keeps_rare_family_despite_different_menu_and_pair_counts():
    data = D.Data.__new__(D.Data)
    data.by_seed = {11: [0], 22: [1, 2]}
    data.menu_pairs = {0: [0], 1: [4, 5], 2: [8, 9, 10]}
    ids = data.sample([dict(seed=11), dict(seed=22)], np.array([[.49, .99, .99], [.5, .99, .99]]))
    np.testing.assert_array_equal(ids, [0, 10])
