import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('signal_inventory', ROOT/'docs/experiments/research-signal-inventory.py')
H = importlib.util.module_from_spec(spec); spec.loader.exec_module(H)


def run(actions, status='death'):
    return dict(status=status,
        prefix=[dict(kind='outside',before=f'state-{i}',action=a) for i,a in enumerate(actions)],
        policy_samples=[dict(active=[0,1],chosen=a,parent=0,base_scores=[0.,0.],probabilities=[.5,.5],
                             features=[[[0,1.],[811,.25]],[[0,1.],[811,.25]]]) for a in actions])


def test_selection_is_unchanged_by_any_terminal_labels():
    rows = [run([a]) for a in [0,1,0,1]]
    chosen = H.split_support(rows); assert len(chosen) == 1
    for mask in range(16):
        other = copy.deepcopy(rows)
        for i,row in enumerate(other):row['status'] = 'heart_win' if mask & (1<<i) else 'death'
        assert H.split_support(other) == chosen


def test_two_examples_per_action_do_not_imply_discovery_and_confirmation_support():
    assert H.split_support([run([a]) for a in [0,0,1,1]]) == []
    assert len(H.split_support([run([a]) for a in [0,1,1,0]])) == 1
    rows = [run([a,b]) for a,b in [(0,0),(1,1),(0,1),(1,0)]]
    assert [r['prefix_index'] for r in H.split_support(rows)] == [0]


def test_different_collecting_probabilities_cannot_be_pooled():
    rows = [run([a]) for a in [0,1,0,1]]
    rows[2]['policy_samples'][0]['probabilities'] = [.2,.8]
    with pytest.raises(AssertionError):H.split_support(rows)
