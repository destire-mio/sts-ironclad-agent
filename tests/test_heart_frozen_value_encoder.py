from pathlib import Path
import sys
from types import SimpleNamespace as S

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_parent_state_value as V


def test_heart_updates_change_output_but_not_frozen_sparse_encoder():
    torch.set_num_threads(1)
    torch.manual_seed(77)
    model = V.P.auxiliary_model(12, 0)
    model.tail[-1] = torch.nn.Linear(64, 1)
    torch.nn.init.zeros_(model.tail[-1].weight); torch.nn.init.zeros_(model.tail[-1].bias)
    model.requires_grad_(False); model.tail[-1].requires_grad_(True)
    assert sum(p.numel() for p in model.parameters() if p.requires_grad) == 65
    initial = {key: value.clone() for key, value in model.state_dict().items()}
    values = torch.rand(6, 12)
    targets = torch.tensor([0., 0., 0., 1., 0., 0.])
    data = S(sample=V.Data.sample,
             batch=lambda ids, allowed: (values[ids].to_sparse(), targets[ids]))
    V.fit(model, data, [dict(seed=8, begin=0, end=6)], 8, 0, recipe=V.recipe_for('E172'))
    current = model.state_dict()
    assert all(torch.equal(value, current[key]) for key, value in initial.items() if not key.startswith('tail.3.'))
    assert not torch.equal(initial['tail.3.weight'], current['tail.3.weight'])
    with torch.inference_mode():
        assert not torch.equal(model(values.to_sparse()).sigmoid(), torch.full((6, 1), .5))
