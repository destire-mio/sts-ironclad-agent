"""Audit denser old card consequences without new rollouts or model fitting.

The endpoint is the first subsequent already-audited direct mapped combat
(monster, elite or boss). Event combats can precede it, so it must not be
described as the next physical fight or a pure isolated card-mechanics effect.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(root):
    plan = json.loads((root / 'protocol.json').read_text())
    registration = json.loads((root / 'registration.json').read_text())
    for path, digest in registration['hashes'].items():
        assert sha(path) == digest, path
    source = Path(plan['source'])
    sys.path.insert(0, str(source / 'program'))
    import heart_paired_afterstate_value as A
    E, O = A.E, A.O
    source_plan = A.registered(source)
    review = E.read(source / 'training-review.json')
    assert review['status'] == 'complete_reviewed' and not review['learning_gate_passed']
    assert review['learning_completion_sha256'] == E.sha(source / 'learning/completion.json')
    combat_source = Path(plan['combat_source'])
    combat_review = E.read(combat_source / 'data-review.json')
    assert combat_review['status'] == 'complete_reviewed'
    assert combat_review['data_completion_sha256'] == E.sha(combat_source / 'data/completion.json')
    E.proof(combat_source / 'data', 'completion.json')
    store = O.Store(Path(source_plan['learning_source']) / 'store')
    rows = E.read(source / 'data/rows.json')
    pairs = np.load(source / 'data/pairs.npy', allow_pickle=False)
    heart = np.load(Path(source_plan['value_source']) / 'data/targets.npy', allow_pickle=False)
    exact = np.load(Path(source_plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    depth = exact['maximum_terminal_distance']
    edges = np.load(combat_source / 'data/edges.npy', allow_pickle=False)
    targets = np.load(combat_source / 'data/targets.npy', allow_pickle=False)
    seeds = np.load(combat_source / 'data/seed.npy', allow_pickle=False)
    rooms = np.load(combat_source / 'data/room.npy', allow_pickle=False)
    battle_counts = np.load(combat_source / 'data/battle_count.npy', allow_pickle=False)
    assert len(edges) == len(np.unique(edges)) == 234836
    selected = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    assert len(selected) == len(np.unique(store.edge_state[selected])) == store.states
    parent_edge = np.empty(store.states, dtype=np.int64)
    parent_edge[store.edge_state[selected]] = selected
    nonterminal = selected[np.logical_not(store.done[selected])]
    assert np.all(depth[store.next_state[nonterminal]] < depth[store.edge_state[nonterminal]])
    indexed = np.full(len(store.edge_state), -1, dtype=np.int64)
    indexed[edges] = np.arange(len(edges))
    first = np.full(store.states, -1, dtype=np.int64)
    distance = np.zeros(store.states, dtype=np.int64)
    for state in np.argsort(depth, kind='stable'):
        edge = parent_edge[state]
        if indexed[edge] >= 0:
            first[state] = indexed[edge]
        elif not store.done[edge]:
            successor = store.next_state[edge]
            first[state] = first[successor]
            distance[state] = distance[successor]+1
    ends = np.array([f['end'] for f in store.families]); family_seeds = np.array([f['seed'] for f in store.families])
    # Independent path walks from every actual afterstate verify memoized joins
    # and stop at the first audited combat rather than a chosen later endpoint.
    successors = np.unique([s for row in rows for s in row['successors']])
    walk_steps = 0
    for start in successors:
        owner = family_seeds[np.searchsorted(ends, start, side='right')]
        state, visited = int(start), set()
        while True:
            assert state not in visited
            visited.add(state); walk_steps += 1
            assert family_seeds[np.searchsorted(ends, state, side='right')] == owner
            edge = parent_edge[state]
            if indexed[edge] >= 0:
                assert first[start] == indexed[edge] and seeds[first[start]] == owner
                break
            if store.done[edge]:
                assert first[start] == -1
                break
            state = int(store.next_state[edge])
    counts = Counter(pairs=len(pairs), afterstates=len(successors), missing_afterstates=int((first[successors] < 0).sum()))
    family_counts, details = {}, []
    for row_id, candidate in pairs:
        row = rows[row_id]; left = row['successors'][candidate]; right = row['successors'][row['parent']]
        a, b = int(first[left]), int(first[right])
        heart_difference = int(heart[left]-heart[right])
        family_counts.setdefault(row['seed'], Counter(pairs=0)); family = family_counts[row['seed']]
        family['pairs'] += 1
        counts['heart_ties'] += int(heart_difference == 0)
        detail = dict(row=int(row_id), candidate=int(candidate), alternative_combat=a, parent_combat=b,
                      heart_difference=heart_difference, covered=a >= 0 and b >= 0)
        if a < 0 or b < 0:
            counts['missing_pairs'] += 1
        else:
            difference = targets[a]-targets[b]
            informative = abs(float(difference[0])) >= plan['hp_difference_threshold'] or difference[1] != 0
            detail.update(combat_difference=difference.tolist(), informative=bool(informative))
            counts['covered_pairs'] += 1
            counts['resource_informative'] += int(informative)
            counts['survival_informative'] += int(difference[1] != 0)
            counts['heart_ties_with_resource_information'] += int(heart_difference == 0 and informative)
            counts['same_room_kind'] += int(rooms[a] == rooms[b])
            counts['single_fight_both_endpoints'] += int(battle_counts[a] == battle_counts[b] == 1)
            family['resource_informative'] += int(informative)
        details.append(detail)
    informative_families = sum(c['resource_informative'] > 0 for c in family_counts.values())
    passed = counts['resource_informative'] >= plan['minimum_pair_fraction']*len(pairs) and informative_families >= plan['minimum_family_fraction']*len(family_counts)
    out = root / 'data'; out.mkdir()
    np.save(out / 'first_combat.npy', first, allow_pickle=False)
    E.write(out / 'pairs.json', details)
    report = dict(status='complete_reviewed', experiment='E177', counts=dict(counts),
        families=len(family_counts), informative_families=informative_families, coverage_gate_passed=passed,
        checked_parent_path_states=walk_steps, all_afterstate_endpoints_independently_walked=True,
        mapped_combat_distance_quantiles=np.quantile(distance[successors[first[successors] >= 0]], [0, .5, .9, 1]).tolist(),
        source_native_combat_proofs_reused=True, new_native_replays=0, new_games=0, optimizer_updates=0,
        policy_adoption=False, registration_sha256=E.sha(root / 'registration.json'),
        source_training_review_sha256=E.sha(source / 'training-review.json'),
        combat_source_review_sha256=E.sha(combat_source / 'data-review.json'), runner_sha256=E.sha(__file__),
        limits=plan['limits'])
    E.write(out / 'report.json', report)
    E.write(out / 'completion.json', dict(status='complete', hashes={p.name: E.sha(p) for p in out.iterdir()}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
