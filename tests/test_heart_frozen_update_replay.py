import importlib.util
from pathlib import Path
import random

import numpy as np
import pytest


spec = importlib.util.spec_from_file_location('frozen_update', Path(__file__).parents[1]/'agent/heart_frozen_update_replay.py')
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)


def test_same_stream_accounts_for_forced_choices_and_first_divergence():
    seed = 27; rng = random.Random(seed)
    u = [rng.random() for _ in range(3)]
    p = [[1.], [.4, .6], [.8, .2]]; active = [[4], [1, 3], [2, 9]]
    records = [dict(active=a, probabilities=v, uniform=z, chosen=a[F.categorical(v, z)])
               for a, v, z in zip(active, p, u, strict=True)]
    assert F.first_change(records, p, seed) is None
    altered = [[1.], [1., 0.] if records[1]['chosen'] == 3 else [0., 1.], p[2]]
    assert F.first_change(records, altered, seed) == 1
    records[1]['uniform'] += .01
    with pytest.raises(AssertionError):
        F.first_change(records, p, seed)


def test_family_accounting_keeps_repeated_games_together():
    before = [[1, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0]]
    after = [[0, 1, 1, 0], [0, 0, 0, 0], [1, 0, 0, 0]]
    result = F.comparisons(before, after)
    assert result['candidate_only'] == 3 and result['baseline_only'] == 2
    assert result['improved_families'] == 2 and result['harmed_families'] == 1
    assert result['family_net_gain_histogram'] == {'-1': 1, '1': 2}
    with pytest.raises(AssertionError):
        F.comparisons([[1, 0]], [[0, 0]])


def test_categorical_preserves_zeros_and_boundary_selection():
    assert F.categorical([0., .25, 0., .75, 0.], .25) == 3
    assert F.categorical([0., 1., 0.], 0.) == 1
    assert F.categorical([0., 1., 0.], np.nextafter(1., 0.)) == 1
    with pytest.raises(AssertionError):
        F.categorical([.2, .3], .1)
