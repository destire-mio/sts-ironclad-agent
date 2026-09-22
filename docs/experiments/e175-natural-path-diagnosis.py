"""Read-only first-Act2 card diagnosis along the actual fixed-parent graph path.

This post-hoc scope check does not change E175's failed learning gate, train a
model, deploy stored successors or run games. It retains every initial family.
"""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_paired_afterstate_value as A
    E, O = A.E, A.O
    plan = A.registered(root)
    reviewed = E.read(root / 'training-review.json')
    assert reviewed['status'] == 'complete_reviewed' and not reviewed['learning_gate_passed']
    assert reviewed['learning_completion_sha256'] == E.sha(root / 'learning/completion.json')
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = A.Data(store, root / 'data', Path(plan['value_source']) / 'data', plan['input_columns'])
    edges = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    assert len(edges) == store.states and len(np.unique(store.edge_state[edges])) == store.states
    parent_edge = np.empty(store.states, dtype=np.int64)
    parent_edge[store.edge_state[edges]] = edges
    choices = {}
    for fold in range(3):
        for row in E.read(root / 'learning' / f'fold-{fold}/held-choices.json'):
            assert O.T.fold(row['seed']) == fold
            choices[data.rows[row['row']]['state']] = row
    before = {r['state']: r for r in E.read(Path(plan['ranking_source']) / 'choices.json')}
    scoped = {r['state']: r for r in data.rows if r['act'] == 2}
    initial = {r['seed']: r for r in data.rows if r['act'] == 1 and r['floor'] == 1}
    references = {r['seed']: r for r in E.read(Path(plan['natural_source']) / 'fit-references.json')}
    assert len(initial) == len(references) == 1536
    results, path_steps = [], 0
    for family in store.families:
        root_row = initial[family['seed']]
        original = int(data.value.targets[root_row['state']])
        assert original == references[family['seed']]['target']
        state, visited, match = root_row['state'], set(), None
        while True:
            assert family['begin'] <= state < family['end'] and state not in visited
            visited.add(state); path_steps += 1
            assert int(data.value.targets[state]) == original
            if state in scoped:
                match = scoped[state]
                break
            edge = parent_edge[state]
            if store.done[edge]:
                assert int(store.reward[edge]) == original
                break
            state = int(store.next_state[edge])
        result = dict(seed=family['seed'], parent=original, e170=original, e175=original,
                      available=original, reached=False, e170_changed=False, e175_changed=False)
        if match:
            current, control = choices[state], before[state]
            labels = data.value.targets[match['successors']].astype(int).tolist()
            assert labels == current['labels'] == control['labels'] and labels[match['parent']] == original
            result.update(state=state, reached=True, e170=labels[control['chosen']], e175=labels[current['chosen']],
                available=max(labels), e170_changed=control['chosen'] != match['parent'],
                e175_changed=current['chosen'] != match['parent'])
        results.append(result)
    def summarize(rows):
        totals = dict(families=len(rows), reached=sum(r['reached'] for r in rows), parent=sum(r['parent'] for r in rows),
                      available=sum(r['available'] for r in rows))
        for model in ('e170', 'e175'):
            totals[model] = dict(wins=sum(r[model] for r in rows), changed=sum(r[model+'_changed'] for r in rows),
                gained=sum(r[model] > r['parent'] for r in rows), lost=sum(r[model] < r['parent'] for r in rows))
        return totals
    report = dict(status='complete_reviewed', experiment='E175_posthoc_natural_path_diagnosis',
        all_families=summarize(results), folds={str(f): summarize([r for r in results if O.T.fold(r['seed']) == f]) for f in range(3)},
        matched_parent_path_states=path_steps, all_parent_labels_equal_natural_references=True,
        new_games=0, optimizer_updates=0, policy_adoption=False, original_gate_remains_failed=True,
        training_review_sha256=E.sha(root / 'training-review.json'), runner_sha256=E.sha(__file__),
        limits='Post-hoc one-change Act2 scope check along reviewed old parent paths. Every initial family remains in the denominator. These are looked-up fixed-continuation outcomes, not live policy or untouched-seed results.')
    E.write(root / 'natural-path-diagnosis-rows.json', results)
    report['rows_sha256'] = E.sha(root / 'natural-path-diagnosis-rows.json')
    E.write(root / 'natural-path-diagnosis.json', report)
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
