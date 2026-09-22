"""Independent auxiliary paired-combat data and NumPy prediction review."""
import argparse
from pathlib import Path
import sys

import numpy as np
import torch


def ids_and_targets(data, pairs):
    left, right = [], []
    for pair in pairs:
        row_id, candidate = data.pairs[pair]; row = data.rows[row_id]
        left.append(row['successors'][candidate]); right.append(row['successors'][row['parent']])
    ids = np.array(left+right)
    values = data.targets[data.first[ids]].astype(np.float64)
    return ids, values[:len(pairs)]-values[len(pairs):]


def matrix(store, ids, columns):
    result = np.zeros((len(ids), store.spec['width']+store.spec['descriptor_dim']), dtype=np.float32)
    permitted = set(columns)
    for i, state in enumerate(ids):
        a, b = store.shared.ptr[state:state+2]
        for col, value in zip(store.shared.cols[a:b], store.shared.values[a:b]):
            if col in permitted: result[i, col] = value
    return result


def predict(weights, values):
    for layer in ('input', 'tail.1', 'tail.3'):
        values = values @ weights[layer+'.weight'].numpy().T+weights[layer+'.bias'].numpy()
        if layer != 'tail.3': values = values/(1+np.exp(np.clip(-values, -80, 80)))
    n = len(values)//2
    return values[:n].astype(np.float64)-values[n:].astype(np.float64)


def errors(weights, data, pairs, columns):
    total, baseline = np.zeros(2), np.zeros(2)
    for at in range(0, len(pairs), 128):
        group = pairs[at:at+128]
        ids, labels = ids_and_targets(data, group)
        predictions = predict(weights, matrix(data.store, ids, columns))
        total += ((predictions-labels)**2).sum(axis=0)
        baseline += (labels**2).sum(axis=0)
    return total/len(pairs), baseline/len(pairs)


def main(root, phase):
    sys.path.insert(0, str(root / 'program'))
    import heart_card_combat_delta as D
    E, O = D.E, D.O
    plan = D.registered(root)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store'); data = D.Data(store, plan)
    source = Path(plan['value_source']); width = store.spec['width']+store.spec['descriptor_dim']
    target = Path(plan['target_source'])
    pairs = E.read(target / 'data/pairs.json')
    eligible = [i for i, row in enumerate(pairs) if row['covered']]
    assert eligible == sorted(i for group in data.menu_pairs.values() for i in group)
    maximum = 0.
    if phase == 'data':
        for i in eligible:
            _, actual = ids_and_targets(data, [i])
            np.testing.assert_allclose(actual[0], pairs[i]['combat_difference'], atol=1e-7, rtol=0)
        warm_checks = 0
        for fold in range(3):
            families = [f for f in store.families if O.T.fold(f['seed']) != fold]
            inner, _ = O.inner_partition(families)
            for nested in (True, False):
                model, retained = D.warm_model(source, width, fold, nested)
                original = D.A.warm_model(source, width, fold, nested).state_dict()
                for key, value in model.state_dict().items():
                    if not key.startswith('tail.3.'): assert torch.equal(value, original[key])
                    else: assert torch.count_nonzero(value) == 0
                assert torch.equal(retained['weight'], original['tail.3.weight'])
                assert torch.equal(retained['bias'], original['tail.3.bias']); warm_checks += 1
            model, _ = D.warm_model(source, width, fold, True)
            # Nonzero discarded fixture exposes inference/target paths hidden
            # by a zero auxiliary head; no fitted fixture becomes a candidate.
            D.fit(model, data, inner, 8, fold)
            chosen = data.sample(inner, np.random.default_rng(2026092378+100+fold).random((32, 3)))
            values, labels = data.batch(chosen, {f['seed'] for f in inner})
            ids, expected = ids_and_targets(data, chosen)
            np.testing.assert_allclose(D.differences(labels).numpy(), expected, atol=1e-7, rtol=0)
            with torch.inference_mode(): actual = D.differences(model(values)).numpy()
            independent = predict(model.state_dict(), matrix(store, ids, plan['input_columns']))
            np.testing.assert_allclose(actual, independent, atol=1e-6, rtol=0)
            maximum = max(maximum, float(np.abs(actual-independent).max()))
            held = next(f for f in store.families if O.T.fold(f['seed']) == fold)
            forbidden = data.menu_pairs[data.by_seed[held['seed']][0]][0]
            try:
                data.batch(np.array([forbidden]), {f['seed'] for f in inner})
                raise AssertionError('held target allowed')
            except ValueError as exc:
                assert 'held family' in str(exc)
        report = dict(status='complete_reviewed', experiment='E178', pair_targets_recomputed=len(eligible),
            excluded_missing_pairs=len(pairs)-len(eligible), eligible_families=len(data.by_seed), warm_checks=warm_checks,
            independent_nonzero_pairs=96, maximum_numpy_error=maximum, held_target_rejections=3,
            discarded_fixture_updates=24, candidate_optimizer_updates=0, new_games=0, new_native_replays=0,
            target_completion_sha256=E.sha(target / 'data/completion.json'), reviewer_sha256=E.sha(__file__))
        E.write(root / 'data-review.json', report); print(report, flush=True); return
    E.proof(root / 'learning', 'completion.json')
    end = E.read(root / 'train-control/exit.json'); process = root / 'train-execution/pipeline-process-exit.json'
    assert end['status'] == 'train_complete' and end['exit_code'] == 0
    assert end['owned_exit_sha256'] == E.sha(process) and end['completion_sha256'] == E.sha(root / 'learning/completion.json')
    assert E.read(process)['exit_code'] == 0 and E.read(process)['cleanup']['clean']
    reports, checkpoint_count = [], 0
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'; roles = E.read(directory / 'roles.json')
        old_roles = E.read(source / 'learning' / f'fold-{fold}/roles.json')
        for key in ('inner_train', 'inner_validation', 'fit', 'held'): assert roles[key] == old_roles[key]
        rng = np.random.default_rng(D.RECIPE['seed']+2000+fold)
        for key, role in (('validation_pairs', 'inner_validation'), ('held_pairs', 'held')):
            families = [f for f in store.families if f['seed'] in roles[role]]
            expected = []
            for a, b, c in rng.random((D.RECIPE['validation_draws'], 3)):
                family = families[int(a*len(families))]
                menus = data.by_seed[family['seed']]; candidates = data.menu_pairs[menus[int(b*len(menus))]]
                expected.append(candidates[int(c*len(candidates))])
            assert roles[key] == expected
        curve = E.read(directory / 'stopping.json')
        assert [r['step'] for r in curve] == D.RECIPE['checkpoints']
        recomputed = []
        for row in curve:
            weights = torch.load(directory / f'inner-{row["step"]}.pt', weights_only=True, map_location='cpu')
            if row['step'] == 0:
                warm, _ = D.warm_model(source, width, fold, True)
                assert all(torch.equal(value, warm.state_dict()[key]) for key, value in weights.items())
            actual, baseline = errors(weights, data, roles['validation_pairs'], plan['input_columns'])
            np.testing.assert_allclose(actual, row['mse'], atol=1e-6, rtol=0)
            np.testing.assert_allclose(baseline, row['zero_baseline_mse'], atol=1e-6, rtol=0)
            maximum = max(maximum, float(np.abs(actual-row['mse']).max())); checkpoint_count += 1
            recomputed.append(dict(step=row['step'], mean_mse=float(np.mean(actual))))
        selected = min(recomputed, key=lambda r: (r['mean_mse'], r['step']))['step']
        saved = torch.load(directory / 'auxiliary.pt', weights_only=True, map_location='cpu')
        assert saved['model_type'] == 'card_combat_delta_auxiliary' and saved['prediction_only']
        assert saved['feature_spec'] == store.spec and saved['input_columns'] == plan['input_columns']
        assert saved['provenance'] == dict(fold=fold, fit_families=roles['fit'], selected_steps=selected,
            recipe=D.RECIPE, value_sha256=E.sha(source / 'learning' / f'fold-{fold}/value.pt'))
        _, head = D.warm_model(source, width, fold, False)
        assert all(torch.equal(value, head[key]) for key, value in saved['retained_heart_head'].items())
        actual, baseline = errors(saved['model_state'], data, roles['held_pairs'], plan['input_columns'])
        report = E.read(directory / 'report.json'); assert report['selected_steps'] == selected
        np.testing.assert_allclose(actual, report['held_mse'], atol=1e-6, rtol=0)
        np.testing.assert_allclose(baseline, report['zero_baseline_mse'], atol=1e-6, rtol=0)
        reports.append(dict(fold=fold, selected_steps=selected, held_mse=actual.tolist(), zero_baseline_mse=baseline.tolist()))
    error = float(np.mean([r['held_mse'] for r in reports])); baseline = float(np.mean([r['zero_baseline_mse'] for r in reports]))
    passed = error <= D.RECIPE['relative_mse_gate']*baseline and all(np.mean(r['held_mse']) < np.mean(r['zero_baseline_mse']) for r in reports)
    updates = 3*D.RECIPE['steps']+sum(r['selected_steps'] for r in reports)
    recorded = E.read(root / 'learning/report.json')
    assert bool(passed) == recorded['auxiliary_gate_passed'] and updates == recorded['auxiliary_optimizer_updates']
    result = dict(status='complete_reviewed', experiment='E178', folds=reports, held_mse=error, zero_baseline_mse=baseline,
        auxiliary_gate_passed=bool(passed), auxiliary_optimizer_updates=updates,
        independent_checkpoints=checkpoint_count, independent_held_pairs=3*D.RECIPE['validation_draws'], maximum_numpy_error=maximum,
        heart_optimizer_updates=0, new_games=0, policy_adoption=False,
        data_review_sha256=E.sha(root / 'data-review.json'), learning_completion_sha256=E.sha(root / 'learning/completion.json'),
        controller_exit_sha256=E.sha(root / 'train-control/exit.json'), reviewer_sha256=E.sha(__file__),
        limits='Auxiliary mapped-combat effect prediction only, not an adopted Heart policy or natural/unseen result.')
    E.write(root / 'training-review.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--phase', choices=('data', 'train'), required=True)
    args = parser.parse_args(); main(args.study.resolve(), args.phase)
