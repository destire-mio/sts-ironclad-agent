"""Check fixed-parent pair labels, family ownership and actual afterstate inputs."""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_paired_afterstate_value as A
    E, O = A.E, A.O
    plan = A.registered(root)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    source = Path(plan['value_source'])
    E.proof(source / 'learning', 'completion.json')
    rank = Path(plan['ranking_source'])
    admitted = E.read(rank / 'choices.json')
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = A.Data(store, root / 'data', source / 'data', plan['input_columns'])
    old = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    parent_values, best_values = old['parent_value'], old['observed_best']
    assert np.array_equal(parent_values, data.value.targets)
    pairs, changed, matrix = [], set(), Counter()
    for i, (row, saved) in enumerate(zip(data.rows, admitted, strict=True)):
        assert {k: row[k] for k in saved if k in row} == {k: saved[k] for k in saved if k in row}
        state = row['state']; owners = data.value.seeds[np.searchsorted(data.value.ends, [state]+row['successors'], side='right')]
        assert all(int(seed) == row['seed'] for seed in owners)
        assert row['successors'] == store.next_state[row['edges']].tolist()
        assert not store.done[row['edges']].any()
        assert store.edge_action[row['edges'][row['parent']]] == store.parent[state]
        actual = parent_values[row['successors']]
        assert actual.tolist() == saved['labels'] and actual[row['parent']] == parent_values[state]
        assert row['pair_begin'] == len(pairs)
        for j, successor in enumerate(row['successors']):
            if j != row['parent']:
                pairs.append([i, j])
                before = best_values[successor]-best_values[row['successors'][row['parent']]]
                after = parent_values[successor]-parent_values[row['successors'][row['parent']]]
                matrix[f'{int(before)}->{int(after)}'] += 1
                if before != after: changed.add(state)
        assert row['pair_end'] == len(pairs)
    assert np.array_equal(np.array(pairs), data.pairs)
    assert len(changed) == 190 and sum(n for key, n in matrix.items() if key.split('->')[0] != key.split('->')[1]) == 570
    assert dict(matrix) == E.read(root / 'data/report.json')['old_to_fixed_parent_differences']['all']
    # Only already admitted deterministic successors are used. E171's native
    # state/scope audit is reused by hash; this review does not replay games.
    check_path = Path(__file__).with_name('e176-review.py')
    spec = importlib.util.spec_from_file_location('independent_afterstate', check_path)
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    maximum, warm_checks = 0., 0
    width = store.spec['width']+store.spec['descriptor_dim']
    for fold in range(3):
        fit = [f for f in store.families if O.T.fold(f['seed']) != fold]
        inner, valid = O.inner_partition(fit)
        held = [f for f in store.families if O.T.fold(f['seed']) == fold]
        for nested, families in ((True, inner), (False, fit)):
            model = A.warm_model(source, width, fold, nested)
            original_dir = source / 'learning' / f'fold-{fold}'
            step = E.read(original_dir / 'report.json')['selected_steps']
            original = torch.load(original_dir / (f'inner-{step}.pt' if nested else 'value.pt'), weights_only=True, map_location='cpu')
            if not nested: original = original['model_state']
            assert all(torch.equal(value, original[key]) for key, value in model.state_dict().items()); warm_checks += 1
            ids = data.subset(families)[:16]
            native = A.score(model, data, ids, {f['seed'] for f in families})
            independent = check.choices(original, data, ids, True, plan['input_columns'])
            maximum = max(maximum, check.verify_choices(native, independent))
        forbidden_row = data.by_seed[held[0]['seed']][0]
        try:
            data.batch(np.array([data.rows[forbidden_row]['pair_begin']]), np.array([fit[0]['begin']]), {f['seed'] for f in fit})
            raise AssertionError('held-family label was accepted')
        except ValueError as error:
            assert 'held family' in str(error)
    families = [f for f in store.families if O.T.fold(f['seed']) != 0]
    inner, _ = O.inner_partition(families)
    model = A.warm_model(source, width, 0, True)
    before = {k: v.clone() for k, v in model.state_dict().items()}
    A.fit(model, data, inner, 8, 0, recipe=plan['recipe'])
    assert any(not torch.equal(value, before[key]) for key, value in model.state_dict().items())
    assert all(bool(torch.isfinite(value).all()) for value in model.state_dict().values())
    result = dict(status='complete_reviewed', experiment='E176', actual_afterstate_rows=len(data.rows),
        fixed_parent_pairs=len(pairs), initial_natural_families=1536, changed_comparison_labels=570,
        changed_states=len(changed), warm_weight_checks=warm_checks, independent_menu_checks=96,
        maximum_numpy_error=maximum, held_family_guards=3, discarded_fixture_updates=8,
        source_scope_review_reused=True, source_scope_sha256=E.sha(rank / 'result.json'),
        data_completion_sha256=E.sha(root / 'data/completion.json'), reviewer_sha256=E.sha(__file__),
        optimizer_candidate_updates=0, new_games=0, new_native_replays=0, policy_adoption=False)
    E.write(root / 'data-review.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
