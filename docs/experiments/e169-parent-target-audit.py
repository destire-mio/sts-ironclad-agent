"""Audit dense fixed-parent state returns before designing a state-value fit."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np


def main(source, diagnosis, natural, output):
    sys.path.insert(0, str(source / 'program'))
    import heart_offline_control as O
    E = O.E
    review = E.read(diagnosis / 'result-review.json')
    assert review['status'] == 'complete'
    assert review['graph_bellman_expectile_parent_maximum_and_acyclicity_verified']
    exact_path = diagnosis / 'exact-observed-values.npz'
    assert E.sha(exact_path) == review['exact_values_sha256']
    store = O.Store(source / 'store')
    data = np.load(exact_path, allow_pickle=False)
    parent, best, depth = data['parent_value'], data['observed_best'], data['maximum_terminal_distance']
    assert len(parent) == store.states == 2039965
    assert np.isin(parent, [0., 1.]).all()
    edges = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    assert len(edges) == store.states
    assert np.array_equal(np.sort(store.edge_state[edges]), np.arange(store.states))
    expected = np.where(store.done[edges], store.reward[edges], parent[store.next_state[edges]])
    np.testing.assert_array_equal(parent[store.edge_state[edges]], expected)
    ongoing = edges[~store.done[edges]]
    assert np.all(depth[store.edge_state[ongoing]] > depth[store.next_state[ongoing]])
    refs = E.indexed(E.read(natural / 'fit-references.json'), 'seed', 'reference')
    assert len(refs) == len(store.families) == 1536
    starts = []
    for family in store.families:
        ref = refs[family['seed']]
        value = int(parent[family['begin']])
        assert value == int(ref['status'] == 'heart_win') == ref['target']
        starts.append(value)
    # Raw public act is the fifth allowlisted scalar, normalized by4.
    act_column = store.spec['observations'].index(4)
    positions = np.flatnonzero(store.shared.cols == act_column)
    rows = np.searchsorted(store.shared.ptr, positions, side='right')-1
    assert len(rows) == store.states and np.array_equal(rows, np.arange(store.states))
    acts = np.rint(store.shared.values[positions]*4).astype(int)
    assert np.isin(acts, [1, 2, 3, 4]).all()
    by_act = {str(act): dict(states=int(np.count_nonzero(acts == act)),
        parent_winning_states=int(parent[acts == act].sum())) for act in range(1, 5)}
    result = dict(status='complete_reviewed', experiment='E169_target_audit',
        state_targets=store.states, families=len(store.families), natural_parent_wins=sum(starts),
        winning_state_labels=int(parent.sum()), losing_state_labels=int(len(parent)-parent.sum()),
        parent_edges_checked=len(edges), acyclic_parent_successors_checked=len(ongoing),
        natural_start_targets_checked=len(starts), by_act=by_act,
        states_where_observed_max_differs_from_parent=int(np.count_nonzero(best != parent)),
        optimizer_updates=0, new_games=0, production_adoption=False,
        hashes={str(p): E.sha(p) for p in (exact_path, diagnosis / 'result-review.json',
            source / 'store/completion.json', natural / 'fit-references.json', Path(__file__))},
        next='Test observation-only Heart state-value learning on these fixed-parent outcomes, with family isolation, fitted-only scalar baselines and a frozen recipe before updates. No action choice or afterstate policy is admitted by this audit.',
        limits='These are2,039,965 correlated states within1,536 old families, not independent games. Labels follow the frozen parent, not the observed hindsight maximum. Hidden state/RNG participate only in reference graph identity and labels; value inputs must use the existing public observation whitelist.')
    E.write(output, result)
    print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'diagnosis', 'natural', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    main(args.source.resolve(), args.diagnosis.resolve(), args.natural.resolve(), args.output.resolve())
