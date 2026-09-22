"""Review completed E159 path accounting and all old natural trace prefixes."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np


def main(root):
    registration = __import__('json').loads((root / 'registration.json').read_text())
    source = Path(registration['source'])
    sys.path.insert(0, str(source / 'program'))
    import heart_exact_control as F
    E, O = F.E, F.O
    plan = F.registered(source)
    E.proof(root, 'completion.json')
    assert E.sha(root / 'program/e159-recorded-policy-diagnosis.py') == registration['runner_sha256']
    assert E.sha(source / 'result-review.json') == registration['source_review_sha256']
    store = O.Store(Path(plan['learning_source']) / 'store')
    values = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    graph_source = Path(E.read(Path(plan['learning_source']) / 'protocol.json')['source'])
    continuous = Path(E.read(graph_source / 'protocol.json')['continuous_source'])
    refs = E.indexed(E.read(continuous / 'fit-references.json'), 'seed', 'reference')
    reports = E.read(root / 'fold-reports.json')
    prior = Path(registration['prior_attempt'])
    assert E.sha(prior / 'partial-fold-0.json') == registration['retained_partial_sha256']
    assert reports['0'] == E.read(prior / 'partial-fold-0.json')['report']
    result = E.read(root / 'report.json')
    rows = E.read(root / 'results-private.json')
    assert len(rows) == 4608 and len({(r['fold'], r['seed']) for r in rows}) == 4608
    families = {f['seed']: f for f in store.families}
    paths = {int(s): p for s, p in E.read(root / 'held-paths-private.json').items()}
    assert set(paths) == set(families)
    checked_edges = changed = 0
    for seed, record in paths.items():
        family = families[seed]
        a, b, c, d = (family[k] for k in ('begin', 'end', 'edge_begin', 'edge_end'))
        roots = np.flatnonzero(np.bincount(store.next_state[c:d][~store.done[c:d]] - a, minlength=b-a) == 0)
        assert len(roots) == 1 and record['origin'] == a + roots[0]
        assert values['parent_value'][record['origin']] == int(refs[seed]['status'] == 'heart_win')
        state = record['origin']
        for i, (actual_state, choice) in enumerate(record['path']):
            assert state == actual_state and a <= state < b
            assert 0 <= choice < store.menu_ptr[state+1] - store.menu_ptr[state]
            u, v = store.state_edge_ptr[state:state+2]
            edges = store.state_edge_ids[u:v]
            action = store.menu_ptr[state] + choice
            found = edges[store.edge_action[edges] == action]
            changed += int(action != store.parent[state])
            checked_edges += 1
            if not len(found):
                assert i == len(record['path']) - 1 and record['status'] == 'unknown_unrecorded_action'
            else:
                assert len(found) == 1 and action == store.parent[state]
                edge = int(found[0])
                if store.done[edge]:
                    assert i == len(record['path']) - 1
                    assert record['status'] == ('known_heart_win' if store.reward[edge] else 'known_nonwin')
                else:
                    assert i < len(record['path']) - 1
                    state = int(store.next_state[edge])
    for row in rows:
        assert row['role'] == ('held' if O.T.fold(row['seed']) == row['fold'] else 'fit')
        if row['role'] == 'held':
            assert row['status'] == paths[row['seed']]['status'] and row['steps'] == len(paths[row['seed']]['path'])
        if row['status'] != 'unknown_unrecorded_action':
            assert (row['status'] == 'known_heart_win') == (refs[row['seed']]['status'] == 'heart_win')
    for role in ('fit', 'held'):
        selected = [r for r in rows if r['role'] == role]
        assert dict(Counter(r['status'] for r in selected)) == result['aggregate'][role]['status']
        assert len(selected) == result['aggregate'][role]['assigned']
        assert sum(int(refs[r['seed']]['status'] == 'heart_win') for r in selected) == result['aggregate'][role]['parent_wins']
    natural = Counter(assigned=128)
    for seed in O.T.pilot_seeds(E.read(continuous / 'fit-roles.json')):
        record = paths[seed]
        graph = E.read(graph_source / 'families' / f'{seed}.json.gz')
        raw = E.read(source / 'evaluation/parent_preserving' / f'{seed}.json.gz')
        outside = [s for s in raw['prefix'] if s['kind'] == 'outside']
        assert len(record['path']) <= len(outside)
        for (state, choice), step in zip(record['path'], outside):
            saved = graph['states'][state - families[seed]['begin']]
            assert saved['fingerprint'] == step['before'] and saved['actions'][choice] == step['action']
            natural['checked_outside_actions'] += 1
        if record['status'] == 'unknown_unrecorded_action':
            natural['unrecorded_choice'] += 1
        else:
            assert len(record['path']) == len(outside)
            assert (record['status'] == 'known_heart_win') == (raw['status'] == 'heart_win')
            natural['fully_covered'] += 1
    assert dict(natural) == result['natural_trace_checks']
    review = dict(status='complete_reviewed', experiment='E159', aggregate=result['aggregate'],
        held_paths_verified=len(paths), held_path_choices_verified=checked_edges,
        all_held_changes_are_unrecorded=changed == result['aggregate']['held']['status']['unknown_unrecorded_action'],
        natural_trace_checks=dict(natural), original_partial_matches=True,
        completion_sha256=E.sha(root / 'completion.json'), reviewer_sha256=E.sha(__file__),
        limits='All held graph paths and128 natural prefixes rechecked. Fit rows have family/outcome accounting checks; full fit paths were not saved. Neural inference for every graph path is not independently rerun; E158 natural-policy review and E159 all-branch NumPy probe are separate evidence.',
        optimizer_updates=0, new_games=0, production_adoption=False)
    assert review['all_held_changes_are_unrecorded']
    E.write(root / 'result-review.json', review)
    print(review)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    main(p.parse_args().study.resolve())
