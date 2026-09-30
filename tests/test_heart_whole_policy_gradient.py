"""Terminal credit, behavior probabilities and sampling isolation contracts."""
from pathlib import Path
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'agent'))
import heart_whole_policy_gradient as G


def record(chosen, advantage, probabilities):
    return dict(chosen_active=chosen, advantage=advantage, probabilities=probabilities,
                log_probability=float(np.log(probabilities[chosen])))


def test_common_prefix_has_zero_gradient_for_grouped_full_returns():
    advantages = G.leave_one_out([0, 1, 0, 0])
    scores = torch.tensor([.4, -.3], dtype=torch.float64, requires_grad=True)
    probabilities = scores.detach().softmax(0).tolist()
    loss, _, _, _ = G.objective([scores]*4, [record(0, float(a), probabilities) for a in advantages])
    loss.backward()
    np.testing.assert_allclose(scores.grad.numpy(), [0., 0.], atol=1e-14, rtol=0)


def test_two_required_decisions_receive_positive_terminal_credit():
    # Enumerate all equiprobable paths of a two-step game; only 1,1 wins.
    scores = [torch.zeros(2, dtype=torch.float64, requires_grad=True) for _ in range(2)]
    advantages = G.leave_one_out([0, 0, 0, 1])
    logits, records = [], []
    for path, advantage in zip([(0,0),(0,1),(1,0),(1,1)], advantages):
        for step, chosen in enumerate(path):
            logits.append(scores[step]); records.append(record(chosen, float(advantage), [.5,.5]))
    loss, _, _, _ = G.objective(logits, records); loss.backward()
    for s in scores:
        assert s.grad[1] < 0 < s.grad[0]
        updated = s.detach()-s.grad
        assert updated.softmax(0)[1] > .5


def test_clipping_stops_further_increase_of_overweighted_success():
    scores = torch.tensor([0., 2.], dtype=torch.float64, requires_grad=True)
    _, pg, _, _ = G.objective([scores], [record(1, 1., [.5,.5])])
    pg.backward()
    np.testing.assert_array_equal(scores.grad.numpy(), [0.,0.])


def test_zero_reward_is_kept_but_execution_fault_is_rejected():
    np.testing.assert_array_equal(G.leave_one_out([0,0,0,0]), [0,0,0,0])
    for rewards in ([0,None,1,0], [0,2,0,0], [0,float('nan'),0,1], [0]):
        with pytest.raises((ValueError, TypeError)): G.leave_one_out(rewards)


def test_held_family_cannot_enter_the_on_policy_batch():
    families = list(range(128))
    rows = [dict(seed=s) for s in families for _ in range(4)]
    rows[0]['seed'] = 999
    with pytest.raises(ValueError, match='fitting family'):
        G.fit(None, rows, 0, families, 'unused')


def test_categorical_zero_support_and_shared_sampling_rule():
    probabilities = np.array([0., .25, 0., .75, 0.])
    assert [G.select(probabilities, u) for u in (0., .249, .25, .999)] == [1,1,3,3]
    with pytest.raises(ValueError): G.select(probabilities, 1.)
    values = [G.stream_seed('fit', 0, i, j) for i in range(4) for j in range(4)]
    assert len(values) == len(set(values)) == 16
    assert G.stream_seed('evaluation', 0, 0, 0) not in values
