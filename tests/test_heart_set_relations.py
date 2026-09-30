import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).parents[1]/'agent'))
import heart_set_relations as S

spec = importlib.util.spec_from_file_location('relation_review', Path(__file__).parents[1]/'docs/experiments/e194-review.py')
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)


def inputs():
    return dict(item_ids=torch.tensor([[0, 1, 2, 0]]),
                item_attributes=torch.tensor([[[.2, 0.], [1., .03], [0., 0.], [0., 0.]]], dtype=torch.float64),
                item_mask=torch.tensor([[True, True, True, False]]), candidate_ids=torch.tensor([[0, 1]]),
                candidate_attributes=torch.tensor([[[0., 0., 0.], [.001, 0., 1.]]], dtype=torch.float64),
                context=torch.tensor([[.5, .25]], dtype=torch.float64))


@pytest.mark.parametrize('arm', S.ARMS)
def test_padding_permutation_and_numpy_contract(arm):
    torch.manual_seed(4); model = S.InventoryRelations(3, 2, 4); data = inputs()
    expected = model(data, arm)
    np.testing.assert_allclose(expected.detach().numpy(), R.numpy_relations(model.state_dict(), data, arm), atol=1e-13, rtol=0)
    order = torch.tensor([2, 0, 3, 1]); reordered = dict(data)
    for key in ('item_ids', 'item_attributes', 'item_mask'):
        reordered[key] = data[key][:, order]
    torch.testing.assert_close(model(reordered, arm), expected, atol=1e-13, rtol=0)
    changed_padding = dict(data, item_ids=data['item_ids'].clone(), item_attributes=data['item_attributes'].clone())
    changed_padding['item_ids'][0, 3] = 3; changed_padding['item_attributes'][0, 3] = 100.
    torch.testing.assert_close(model(changed_padding, arm), expected, atol=1e-13, rtol=0)
    swapped = dict(data, candidate_ids=data['candidate_ids'].flip(1), candidate_attributes=data['candidate_attributes'].flip(1))
    torch.testing.assert_close(model(swapped, arm), expected.flip(1), atol=1e-13, rtol=0)


def test_candidate_inventory_attention_and_learning_are_active():
    torch.manual_seed(8); model = S.InventoryRelations(3, 2, 4); data = inputs()
    attention = model(data, 'attention'); pooled = model(data, 'pooled')
    assert not torch.allclose(attention, pooled)
    difference = (attention[:, 0]-attention[:, 1]).square().sum(); difference.backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() and p.grad.abs().sum() > 0 for p in model.queries.parameters())
    assert model.items.weight.grad.abs().sum() > 0
    changed_inventory = dict(data, item_ids=torch.tensor([[0, 3, 2, 0]]))
    assert not torch.allclose(model(changed_inventory, 'attention'), attention)


def test_public_row_tokens_preserve_identity_counts_and_counters():
    shape = dict(cards=2, relics=2, deck_offset=2, relic_offset=6, context_indices=[0, 1],
                 card_offset=0, relic_descriptor_offset=2, candidate_attributes=[4, 5, 6],
                 observation_width=10, descriptor_width=7)
    obs = [.5, .25, .1, .05, 0., 0., 0., 1., 0., .007]
    ds = [[1., 0., 0., 0., .001, .02, 1.], [0., 0., 0., 1., 0., 0., 0.], [0.]*7]
    row = S.encode_row(obs, ds, shape)
    assert row['item_ids'] == [4, 0, 3]
    assert row['item_attributes'] == [[0., 0.], [.1, .05], [1., .007]]
    assert row['candidate_ids'] == [0, 3, 4]
    assert row['context'] == [.5, .25]
    data = S.pack_rows([row], shape)
    assert data['item_mask'].all() and data['candidate_attributes'][0, 0].tolist() == [.001, .02, 1.]
    malformed = [list(value) for value in ds]; malformed[0][2] = 1.
    with pytest.raises(Exception, match='ambiguous'):
        S.encode_row(obs, malformed, shape)
