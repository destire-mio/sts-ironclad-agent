from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from torch.nn import functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_expected_improvement as I


def test_tied_outcomes_do_not_vote_against_a_beneficial_alternative():
    # Eight ties, two gains: the most likely category is a tie, but changing
    # actions has expected benefit .2. The policy must use the expectation.
    logits = torch.tensor([-40., np.log(.8), np.log(.2)], dtype=torch.float64, requires_grad=True)
    labels = torch.tensor([1] * 8 + [2] * 2)
    loss = F.cross_entropy(logits.expand(10, -1), labels)
    gradient, = torch.autograd.grad(loss, logits)
    assert float(gradient.abs().max()) < 1e-12
    assert int(logits.argmax()) == 1
    assert float(I.expected_delta(logits).detach()) == pytest.approx(.2)


def test_loss_probability_offsets_gain_and_parent_stays_zero():
    logits = torch.log(torch.tensor([[.1, .7, .2], [.3, .5, .2], [.2, .6, .2]]))
    np.testing.assert_allclose(I.expected_delta(logits).numpy(), [.1, -.1, 0.], atol=1e-7)
    model = I.new_model(10, 0)
    assert torch.equal(I.expected_delta(model(torch.randn(5, 10))), torch.zeros(5))


def fixture_store():
    return SimpleNamespace(states=4, edges=9,
        edge_state=np.array([0, 1, 2, 0, 2, 1, 2, 3, 3]),
        edge_action=np.array([0, 3, 6, 1, 7, 4, 8, 9, 10]),
        parent=np.array([0, 3, 6, 9]), done=np.ones(9, dtype=bool),
        reward=np.array([0, 1, 0, 1, 0, 0, 0, 1, 0]), next_state=np.zeros(9, dtype=np.int64),
        families=[dict(seed=11, edge_begin=0, edge_end=7), dict(seed=22, edge_begin=7, edge_end=9)])


def test_labels_are_paired_with_parent_at_same_state_and_groups_ignore_edge_order():
    store = fixture_store()
    examples = I.Examples(store, np.zeros(4))
    assert examples.edges.tolist() == [3, 4, 5, 6, 8]
    assert examples.labels.tolist() == [2, 1, 0, 1, 0]
    assert [g.tolist() for g in examples.families[0]['groups']] == [[0], [2], [1, 3]]
    # Fitting access rejects the held family's true rows and negative indices.
    with pytest.raises(ValueError, match='held family'):
        examples.batch(np.array([4]), {11})
    with pytest.raises(ValueError, match='invalid example'):
        examples.batch(np.array([-1]), {11})


def test_paired_features_carry_the_recommended_action_without_outcome_fields():
    descriptor = torch.tensor([[1., 0.], [0., 1.], [2., 3.], [4., 5.]])
    base = torch.tensor([[.1, .2, .3], [.4, .5, .6]])
    store = SimpleNamespace(spec=dict(width=3, descriptor_dim=2), parent=np.array([0, 2]),
        action_features=lambda states, actions: base.to_sparse(),
        descriptors=SimpleNamespace(take=lambda indices: descriptor[indices].to_sparse()))
    actual = I.paired_features(store, np.array([0, 1]), np.array([1, 3])).to_dense()
    torch.testing.assert_close(actual, torch.tensor([[.1, .2, .3, 1., 0.], [.4, .5, .6, 2., 3.]]))
    model = I.new_model(5, 0)
    with torch.no_grad():
        model.tail[-1].weight.fill_(.01)
    torch.testing.assert_close(model(actual), model(actual.to_sparse()))
