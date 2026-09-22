from pathlib import Path
import sys

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_paired_afterstate_value as A


class FixedPair:
    def __init__(self, calibration_feature, calibration_label):
        self.features = torch.tensor([[1.], [0.], [calibration_feature]])
        self.labels = torch.tensor([1., 0., calibration_label])

    def sample(self, families, uniforms):
        return np.array([0]), np.array([2])

    def batch(self, pairs, calibration, allowed):
        return self.features, self.labels


def run(calibration_feature, calibration_label, recipe):
    model = torch.nn.Linear(1, 1)
    torch.nn.init.zeros_(model.weight); torch.nn.init.zeros_(model.bias)
    A.fit(model, FixedPair(calibration_feature, calibration_label), [dict(seed=11)], 8, 0, recipe=recipe)
    return model


def test_pair_only_ranking_cannot_change_when_unrelated_calibration_answers_change():
    first = run(20., 1., A.PAIR_ONLY_RECIPE)
    other = run(20., 0., A.PAIR_ONLY_RECIPE)
    assert all(torch.equal(value, other.state_dict()[key]) for key, value in first.state_dict().items())
    assert first(torch.tensor([[1.]])).item() > first(torch.tensor([[0.]])).item()
    # The old objective provides a control in which these extra labels matter.
    calibrated = run(20., 1., A.RECIPE)
    changed = run(20., 0., A.RECIPE)
    assert not torch.equal(calibrated.weight, changed.weight)


def test_pair_only_ablation_changes_no_sampling_budget_or_selection_setting():
    assert {k: v for k, v in A.PAIR_ONLY_RECIPE.items() if k != 'calibration_weight'} == {
        k: v for k, v in A.RECIPE.items() if k != 'calibration_weight'}
    assert A.PAIR_ONLY_RECIPE['calibration_weight'] == 0
