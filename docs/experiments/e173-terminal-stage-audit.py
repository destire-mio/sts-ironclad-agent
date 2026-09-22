"""Recover fixed-parent terminal categories from complete existing traces.

Categories0..3 mean non-Heart termination in Acts1..4; category4 is Heart.
Act3-only completion belongs to2. These are labels, never policy inputs.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def terminal_category(row):
    assert not row.get('error')
    assert row['status'] in ('death', 'act3_without_heart', 'heart_win')
    assert row['act'] in (1, 2, 3, 4)
    if row['status'] == 'heart_win':
        assert row['act'] == 4 and row['target'] == 1
        return 4
    assert row['target'] == 0
    if row['status'] == 'act3_without_heart':
        assert row['act'] == 3
    return row['act']-1


def main(root):
    registration = json.loads((root / 'registration.json').read_text())
    for path, sha in registration['hashes'].items():
        assert digest(path) == sha, path
    plan = json.loads((root / 'protocol.json').read_text())
    previous = Path(plan['source'])
    sys.path.insert(0, str(previous / 'program'))
    import heart_parent_state_value as V
    E, O = V.E, V.O
    old = V.registered(previous)
    store = O.Store(Path(old['learning_source']) / 'store')
    exact = np.load(Path(old['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    graph_root = Path(E.read(Path(old['learning_source']) / 'protocol.json')['source'])
    proof = E.read(graph_root / 'completion-verification.json')
    assert proof['status'] == 'complete' and proof['zero_faults']
    x = O.C.D.runtime(old['runtime'])
    terminal = np.full(store.edges, -1, dtype=np.int8)
    acts = np.empty(store.states, dtype=np.uint8)
    raw_categories = {}; endings = Counter(); transitions_across_act = Counter()
    route_count = 0
    for number, family in enumerate(store.families):
        path = graph_root / 'families' / f'{family["seed"]}.json.gz'
        assert E.sha(path) == proof['hashes'][str(path)]
        graph = E.read(path)
        assert graph['seed'] == family['seed'] and graph['status'] == 'complete'
        assert len(graph['states']) == family['end']-family['begin']
        assert len(graph['edges']) == family['edge_end']-family['edge_begin']
        acts[family['begin']:family['end']] = [s['act'] for s in graph['states']]
        for route in graph['routes']:
            assert E.sha(route['path']) == route['sha256']
            raw = E.read(route['path'])
            assert raw['seed'] == family['seed'] and raw['target'] == route['target']
            assert raw['engine_sha256'] == x.identity['engine_sha256']
            assert raw['checkpoint_sha256'] == x.identity['model_sha256']
            assert raw['terminal_fingerprint'] == route['terminal_fingerprint']
            prefix, local_edge = route['edges'][-1]
            edge = graph['edges'][local_edge]
            state = graph['states'][edge['state']]
            assert edge['done'] and edge['next_state'] is None
            assert raw['prefix'][prefix]['kind'] == 'outside'
            assert raw['prefix'][prefix]['before'] == state['fingerprint']
            assert raw['prefix'][prefix]['action'] == state['actions'][edge['action']]
            index = family['edge_begin']+local_edge
            assert store.done[index] and store.edge_state[index] == family['begin']+edge['state']
            assert store.reward[index] == raw['target']
            category = terminal_category(raw)
            assert terminal[index] in (-1, category), 'one terminal edge has conflicting source categories'
            terminal[index] = category
            if route['path'] in raw_categories:
                assert raw_categories[route['path']] == category
            raw_categories[route['path']] = category
            endings[(raw['status'], raw['act'])] += 1
            transitions_across_act[(state['act'], raw['act'])] += 1
            route_count += 1
        if (number+1) % 256 == 0:
            print(dict(families=number+1, raw_routes=route_count), flush=True)
    assert route_count == proof['routes'] == 29759
    assert bool((terminal[store.done] >= 0).all())
    assert bool((terminal[~store.done] == -1).all())
    # Independently recover each current act from the public feature store.
    positions = np.flatnonzero(store.shared.cols == store.spec['observations'].index(4))
    state_rows = np.searchsorted(store.shared.ptr, positions, side='right')-1
    assert np.array_equal(state_rows, np.arange(store.states))
    np.testing.assert_array_equal(acts, np.rint(store.shared.values[positions]*4).astype(np.uint8))
    parent_edges = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    assert len(parent_edges) == store.states
    parent = np.empty(store.states, dtype=np.int64)
    parent[store.edge_state[parent_edges]] = parent_edges
    assert len(np.unique(store.edge_state[parent_edges])) == store.states
    done = store.done[parent]
    next_state = store.next_state[parent]
    depth = exact['maximum_terminal_distance']
    assert bool((depth[next_state[~done]] < depth[~done]).all())
    categories = np.full(store.states, -1, dtype=np.int8)
    categories[done] = terminal[parent[done]]
    for state in np.argsort(depth, kind='stable'):
        if not done[state]:
            assert categories[next_state[state]] >= 0
            categories[state] = categories[next_state[state]]
    assert bool(np.isin(categories, range(5)).all())
    np.testing.assert_array_equal(categories, np.where(done, terminal[parent], categories[next_state]))
    np.testing.assert_array_equal(categories == 4, exact['parent_value'] == 1)
    assert bool((categories >= acts.astype(np.int16)-1).all()), 'a later state targets a preceding act death'
    refs = E.read(Path(old['natural_source']) / 'fit-references.json')
    assert [r['seed'] for r in refs] == [f['seed'] for f in store.families]
    initial = Counter()
    for ref, family in zip(refs, store.families):
        assert E.sha(ref['path']) == ref['sha256']
        category = raw_categories.get(ref['path'])
        if category is None:
            category = terminal_category(E.read(ref['path']))
        assert categories[family['begin']] == category
        initial[category] += 1
    assert initial[4] == 149 and sum(initial.values()) == 1536
    out = root / 'data'; out.mkdir()
    np.save(out / 'terminal_categories.npy', categories.astype(np.uint8), allow_pickle=False)
    np.save(out / 'acts.npy', acts, allow_pickle=False)
    for name in ('targets.npy', 'cells.npy'):
        (out / name).symlink_to((previous / 'data' / name).resolve())
    report = dict(status='complete_reviewed', experiment='E173', families=len(store.families),
        states=store.states, routes=route_count, terminal_edges=int(store.done.sum()),
        terminal_category_counts=dict(Counter(map(int, categories))), natural_initial_categories=dict(initial),
        raw_terminal_counts={str(k): v for k, v in endings.items()},
        terminal_source_to_actual_act_counts={str(k): v for k, v in transitions_across_act.items()},
        state_counts_by_current_act_and_end={str(act): np.bincount(categories[acts == act], minlength=5).tolist() for act in range(1, 5)},
        all_parent_category_recursions_verified=True, all_heart_labels_equal_original=True,
        all_current_acts_equal_public_observation=True, impossible_preceding_act_targets=0,
        new_games=0, new_native_replays=0, MCTS_searches=0, optimizer_updates=0,
        source_graph_completion_sha256=E.sha(graph_root / 'completion-verification.json'),
        source_training_review_sha256=E.sha(previous / 'training-review.json'), runner_sha256=E.sha(__file__),
        limits='Existing fully replayed trace provenance is reused and its raw terminal metadata rechecked. This adds training labels, not public future inputs, new games or prediction/policy gains.')
    E.write(out / 'report.json', report)
    E.write(out / 'completion.json', dict(status='complete', hashes={p.name: E.sha(p) for p in out.iterdir() if p.is_file()}))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
