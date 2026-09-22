from pathlib import Path
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_terminal_stage_value as S


def test_public_current_act_excludes_only_impossible_earlier_endings():
    acts = torch.tensor([1, 2, 3, 4])
    probabilities = S.masked_logits(torch.zeros(4, 5), acts).softmax(1)
    torch.testing.assert_close(probabilities.sum(1), torch.ones(4))
    torch.testing.assert_close(probabilities[:, 4], torch.tensor([.2, .25, 1/3, .5]))
    for i, act in enumerate(acts):
        assert bool((probabilities[i, :act-1] == 0).all())
    with pytest.raises(ValueError, match='impossible terminal category'):
        S.terminal_loss(torch.zeros(1, 5), torch.tensor([2]), torch.tensor([4]))


def test_failure_stage_adds_supervision_but_preserves_heart_probability_optimum():
    gradients = []
    for category in (0, 3):
        logits = torch.zeros(1, 5, requires_grad=True)
        S.terminal_loss(logits, torch.tensor([category]), torch.tensor([1])).backward()
        gradients.append(logits.grad)
    assert not torch.equal(*gradients)
    # A calibrated terminal distribution minimizes expected categorical loss;
    # its Heart component is the empirical Heart frequency, not mean progress.
    frequencies = torch.tensor([.23, .29, .25, .13, .10], dtype=torch.float64)
    logits = frequencies.log().detach().requires_grad_()
    loss = -(frequencies*torch.log_softmax(logits, 0)).sum()
    loss.backward()
    assert float(logits.grad.abs().max()) < 1e-12
    torch.testing.assert_close(S.heart_probability(logits[None], torch.tensor([1])), torch.tensor([.1], dtype=torch.float64))


def test_heart_scoring_prefers_more_wins_over_more_late_failures():
    probabilities = torch.tensor([[.01, .01, .01, .92, .05], [.70, .01, .04, .05, .20]])
    assert float((probabilities[0]*torch.arange(5)).sum()) > float((probabilities[1]*torch.arange(5)).sum())
    values = S.heart_probability(probabilities.log(), torch.ones(2, dtype=torch.long))
    assert int(values.argmax()) == 1


def test_held_family_cannot_supply_terminal_stage_training_label():
    data = S.Data.__new__(S.Data)
    data.targets = np.zeros(4, dtype=np.float32)
    data.ends, data.seeds = np.array([2, 4]), np.array([11, 22])
    with pytest.raises(ValueError, match='held family'):
        data.batch(np.array([2]), {11})
