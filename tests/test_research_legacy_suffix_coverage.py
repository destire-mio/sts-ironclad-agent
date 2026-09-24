import copy
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('legacy_coverage', Path(__file__).parents[1]/'docs/experiments/research-legacy-suffix-coverage.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def run(actions):
    return dict(intervention_index=0, prefix=[dict(kind='outside', before=f'state-{i}', action=a) for i, a in enumerate(actions)],
        choices=[dict(fingerprint=f'state-{i}', actions=[0, 1], chosen=a, observation=[], descriptors=[], teacher=0,
                      behavior_probabilities=[.5, .5], act=3, floor=40, screen='MAP') for i, a in enumerate(actions)])


def test_zero_origin_alternatives_does_not_imply_zero_suffix_alternatives():
    rows = [run([0, a]) for a in [0, 0, 1, 1, 0, 0, 1, 1]]
    shared, found = M.forks(rows)
    assert shared == {'3': 2}
    assert len(found) == 1 and found[0]['prefix_index'] == 1
    assert found[0]['all_eight_present'] and found[0]['split_minimum_two']
    for mask in range(256):
        changed = copy.deepcopy(rows)
        for i, row in enumerate(changed):
            row['target'] = bool(mask & (1 << i))
        assert M.forks(changed) == (shared, found)


def test_matching_current_fingerprint_does_not_merge_different_histories():
    rows = [run([a, b]) for a, b in [(0, 0), (0, 1), (1, 0), (1, 1)]*2]
    _, found = M.forks(rows)
    assert len(found) == 3
    assert sum(row['all_eight_present'] for row in found) == 1
    assert len({row['history_sha256'] for row in found if row['prefix_index'] == 1}) == 2


def test_balanced_total_counts_do_not_imply_each_half_has_support():
    _, found = M.forks([run([a]) for a in [0]*4+[1]*4])
    assert len(found) == 1 and not found[0]['split_minimum_one']
