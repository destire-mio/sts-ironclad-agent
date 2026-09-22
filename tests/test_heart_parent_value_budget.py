from pathlib import Path
import sys
from types import SimpleNamespace as S

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_parent_state_value as V


def test_extension_preserves_every_nonbudget_parameter_and_rejects_other_budgets():
    assert V.recipe_for('E169') == V.RECIPE
    extended = V.recipe_for('E170')
    assert extended['steps'] == 20000
    assert extended['checkpoints'] == V.RECIPE['checkpoints'] + [10000, 20000]
    assert {k: v for k, v in extended.items() if k not in ('steps', 'checkpoints')} == {
        k: v for k, v in V.RECIPE.items() if k not in ('steps', 'checkpoints')}
    with pytest.raises(ValueError, match='unregistered value budget'):
        V.recipe_for('E171')


def test_old_and_extended_budget_produce_identical_optimizer_prefix():
    # Equal public states/targets and sampling must yield equal learned weights,
    # not merely the same number of optimizer calls.
    torch.set_num_threads(1)
    raw = torch.tensor([[.3, .4], [.7, .8], [.1, .6], [.9, .2]])
    labels = torch.tensor([0., 1., 1., 0.])
    data = S(sample=V.Data.sample,
             batch=lambda ids, allowed: (raw[ids], labels[ids]))
    family = [dict(seed=9, begin=0, end=4)]
    old = torch.nn.Linear(2, 1)
    extended = torch.nn.Linear(2, 1)
    extended.load_state_dict(old.state_dict())
    initial = old.weight.detach().clone()
    V.fit(old, data, family, 8, 0)
    V.fit(extended, data, family, 8, 0, recipe=V.EXTENDED_RECIPE)
    assert not torch.equal(old.weight, initial)
    assert all(torch.equal(value, extended.state_dict()[key]) for key, value in old.state_dict().items())
