import importlib.util
import itertools
from collections import Counter
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('repeatability',Path(__file__).parents[1]/'docs/experiments/research-legacy-action-repeatability.py')
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def test_teacher_uses_discovery_only_and_negative_confirmation_is_retained():
    assert M.compare([[0],[1]],[[1],[0]])['improvement'] == -1
    assert M.compare([[0],[1]],[[0],[1]])['teacher_alternative']
    assert not M.compare([[1],[1]],[[0],[1]])['teacher_alternative']
    assert M.compare([[1],[1]],[[0],[1]])['improvement'] == 0
    with pytest.raises(AssertionError):
        M.compare([[0],[]],[[0],[1]])


def test_conditional_null_matches_exhaustive_permutations_for_all_group_sizes():
    for a in range(1,4):
        for b in range(1,5-a):
            for wins in range(a+b+1):
                assignments=list(itertools.combinations(range(a+b),wins))
                counts=Counter()
                for positive in assignments:
                    values=[int(i in positive) for i in range(a+b)]
                    counts[round(12*(sum(values[a:])/b-sum(values[:a])/a))] += 1
                arbitrary=[1]*wins+[0]*(a+b-wins)
                assert M.null_distribution([arbitrary[:a],arbitrary[a:]]) == pytest.approx({v:n/len(assignments) for v,n in counts.items()})


def test_exact_convolution_keeps_zero_and_negative_contrasts():
    groups=[[[0],[1]],[[0],[1]]]
    assert M.randomization_p(groups,2) == .25
    assert M.randomization_p(groups,0) == .75
    assert M.randomization_p(groups,-2) == 1
    assert M.randomization_p([],0) == 1
