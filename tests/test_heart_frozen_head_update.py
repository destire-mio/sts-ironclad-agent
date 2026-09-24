import copy
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest
import torch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'agent'))
import heart_frozen_head_update as H
import heart_whole_policy_gradient as G

spec = importlib.util.spec_from_file_location('head_review', ROOT/'docs/experiments/e197-review.py')
V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)


@pytest.mark.parametrize('scale', [.01, 4.])
def test_cached_head_gradient_matches_frozen_network_and_explicit_derivative(scale):
    torch.manual_seed(18)
    old_net = torch.nn.Sequential(torch.nn.Linear(12, 192), torch.nn.ReLU(), torch.nn.Linear(192, 1)).double()
    initial = copy.deepcopy(old_net).requires_grad_(False)
    with torch.no_grad(): old_net[0].bias.add_(.1)
    old_net.requires_grad_(False)
    raw = torch.randn(10, 12, dtype=torch.float64); hidden = old_net[:2](raw).numpy()
    original = old_net[2].weight.detach().flatten().clone()
    weight = original+scale*torch.linspace(-1, 1, 192, dtype=torch.float64)
    base = torch.linspace(-.3, .7, 10, dtype=torch.float64)
    offsets = np.array([0, 3, 7, 10]); old = (base+old_net(raw).flatten()-initial(raw).flatten()).numpy()
    p = np.exp(H.grouped_log_probabilities(old, offsets)); selected = np.array([0, 2, 1])
    data = dict(offsets=offsets, old_logits=old, old_probabilities=p, chosen=selected,
                selected_log=np.log(p[offsets[:-1]+selected]), advantages=np.array([1., -1., 0.]))
    head = torch.nn.Parameter(weight.clone())
    features, before, sizes, rows = H.batch_inputs(hidden, data, [0, 1, 2])
    loss, _, _, ratios = G.objective((before+features @ (head-original)).split(sizes), rows)
    loss.backward()
    independent_gradient, independent_loss = V.manual_gradient(weight.numpy(), original.numpy(), hidden, data, [0, 1, 2])
    np.testing.assert_allclose(independent_gradient, head.grad.numpy(), rtol=0, atol=1e-12)
    assert abs(float(loss.detach())-independent_loss) < 1e-12
    network = copy.deepcopy(old_net); network[2].weight.requires_grad_(True)
    with torch.no_grad(): network[2].weight.copy_(weight[None])
    full_loss, *_ = G.objective((base+network(raw).flatten()-initial(raw).flatten()).split(sizes), rows)
    full_loss.backward()
    assert abs(float(full_loss.detach())-float(loss.detach())) < 1e-12
    np.testing.assert_allclose(head.grad.numpy(), network[2].weight.grad.numpy()[0], rtol=0, atol=1e-12)
    assert network[0].weight.grad is None and network[0].bias.grad is None and network[2].bias.grad is None
    if scale == 4.:
        assert ((ratios.detach()-1).abs() > .2).any()


def test_movement_calibration_matches_target_and_ignores_common_logit_shift():
    old = np.array([.4, -.2, -.7, .1, .9]); direction = np.array([-.4, .7, .5, -.2, .2])
    offsets = np.array([0, 2, 5]); target = H.mean_kl(old, old+2.7*direction, offsets)
    alpha, actual = H.calibrate(old, direction, offsets, target)
    assert abs(alpha-2.7) < 1e-9 and abs(actual-target) < 1e-12
    shifted = old+2.7*direction+np.array([3., 3., -2., -2., -2.])
    assert abs(H.mean_kl(old, shifted, offsets)-target) < 1e-14
    with pytest.raises(AssertionError): H.calibrate(old, np.zeros(5), offsets, target)
    with pytest.raises(AssertionError): H.calibrate(old, direction, offsets, float('nan'))


def test_complete_group_rejects_family_stream_checkpoint_and_fault_substitution():
    streams = [10, 11, 12, 13]
    group = [dict(seed=23, checkpoint_sha256='actor', status='heart_win' if i == 0 else 'death',
                  audit=dict(public_inputs_sampling_state_rng_and_terminal_verified=True), policy_sampling_seed=s)
             for i, s in enumerate(streams)]
    np.testing.assert_array_equal(H.valid_group(group, 23, 'actor', streams), [1., -1/3, -1/3, -1/3])
    for key, value in [('seed', 24), ('checkpoint_sha256', 'different'), ('policy_sampling_seed', 10), ('error', 'timeout'), ('status', 'evaluation_error')]:
        broken = copy.deepcopy(group); broken[1][key] = value
        with pytest.raises(AssertionError): H.valid_group(broken, 23, 'actor', streams)
    with pytest.raises(AssertionError): H.valid_group(group[:3], 23, 'actor', streams[:3])


def test_paired_review_preserves_zero_cells_and_exact_tail():
    result = V.paired([1, 1, 0, 0], [1, 0, 1, 0])
    assert result['net_gain'] == 0 and result['exact_p'] == 1.
    result = V.paired([0]*8, [1]*8)
    assert result['candidate_only'] == 8 and result['baseline_only'] == 0 and result['exact_p'] == 2/256
