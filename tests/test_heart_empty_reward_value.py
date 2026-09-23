import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'agent'))
import heart_empty_reward_value as L


def test_public_eligibility_preserves_rewards_and_parent_potion_choice():
    # 10=reward exit, 21/22=optional inventory operations in this fixture.
    eligible = lambda kinds, parent, reward=True, normal=True: L.empty_reward(
        reward, normal, kinds, parent, 10, 21, 22)
    assert eligible([10], 10)
    assert eligible([10, 21, 22], 10)
    assert not eligible([3, 10], 10)  # An unclaimed card is a real option.
    assert not eligible([10, 21], 21)  # A potion changes the continuation.
    assert not eligible([10], 10, reward=False)
    assert not eligible([10], 10, normal=False)


def test_only_empty_reward_screen_changes_and_source_is_preserved():
    values = torch.tensor([[.4, 1., 0., .2], [.7, 1., 0., .3], [.1, 0., 1., .9]])
    original = values.to_sparse().coalesce()
    expected = values.clone(); expected[0, 1:3] = torch.tensor([0., 1.])
    result = L.normalize(original, np.array([True, False, False]), 1, 2)
    torch.testing.assert_close(result.to_dense(), expected, rtol=0, atol=0)
    torch.testing.assert_close(original.to_dense(), values, rtol=0, atol=0)
    # Repeating the rewrite, or querying with no eligible states, is stable.
    torch.testing.assert_close(L.normalize(result, [True, False, False], 1, 2).to_dense(), expected)
    torch.testing.assert_close(L.normalize(original, [False]*3, 1, 2).to_dense(), values)


def test_flag_shape_mismatch_fails():
    with pytest.raises((ValueError, RuntimeError, AssertionError)):
        L.normalize(torch.eye(3).to_sparse().coalesce(), [True], 1, 2)
