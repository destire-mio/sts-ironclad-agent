"""Independent NumPy card-ranking, family-stopping and outcome review."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import sys

import numpy as np
import torch


def matrix(store, ids, columns):
    out = np.zeros((len(ids), store.spec['width']+store.spec['descriptor_dim']), dtype=np.float32)
    allowed = set(columns)
    for i, state in enumerate(ids):
        a, b = store.shared.ptr[state:state+2]
        for c, value in zip(store.shared.cols[a:b], store.shared.values[a:b]):
            if int(c) in allowed:
                out[i, c] = value
    return out


def predict(weights, values):
    for layer in ('input', 'tail.1', 'tail.3'):
        values = values @ weights[layer+'.weight'].numpy().T+weights[layer+'.bias'].numpy()
        if layer != 'tail.3':
            values /= 1+np.exp(np.clip(-values, -80, 80))
    return (1/(1+np.exp(np.clip(-values[:, 0], -80, 80)))).astype(np.float64)


def choices(weights, data, ids, enabled, columns):
    states = sorted({s for i in ids for s in data.rows[i]['successors']})
    scores = {}
    for at in range(0, len(states), 128):
        group = states[at:at+128]
        values = predict(weights, matrix(data.store, group, columns))
        scores.update(zip(group, map(float, values)))
    out = []
    for i in ids:
        row = data.rows[i]; parent = row['parent']
        probabilities = [scores[s] for s in row['successors']]
        candidate = sorted(range(len(probabilities)), key=lambda j: (-probabilities[j], j != parent, j))[0]
        chosen = candidate if enabled and probabilities[candidate]-probabilities[parent] > 1e-6 else parent
        labels = data.value.targets[row['successors']].astype(int).tolist()
        out.append(dict(row=i, seed=row['seed'], parent=parent, chosen=chosen,
            initial=row['act'] == 1 and row['floor'] == 1, scores=probabilities, labels=labels))
    return out


def summary(choices):
    count = Counter(states=len(choices)); groups = defaultdict(list)
    for row in choices:
        a, b = row['labels'][row['parent']], row['labels'][row['chosen']]
        count.update(parent_wins=a, chosen_wins=b, available_wins=max(row['labels']),
            changed=int(row['chosen'] != row['parent']), gained=int(b > a), lost=int(b < a))
        groups[row['seed']].append(b-a)
    delta = {str(seed): sum(group)/len(group) for seed, group in sorted(groups.items())}
    return dict(count, families=len(delta), family_mean_gain=sum(delta.values())/len(delta), family_deltas=delta)


def same_summary(actual, expected):
    assert actual.keys() == expected.keys()
    for key in actual:
        if key == 'family_mean_gain':
            assert abs(actual[key]-expected[key]) < 1e-12
        else:
            assert actual[key] == expected[key], key


def verify_choices(actual, expected):
    assert len(actual) == len(expected)
    maximum = 0.
    for a, b in zip(actual, expected):
        for key in a:
            if key == 'scores':
                error = max(abs(x-y) for x, y in zip(a[key], b[key]))
                assert error < 1e-6
                maximum = max(maximum, error)
            else:
                assert a[key] == b[key], (key, a['row'])
    return maximum


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_paired_afterstate_value as A
    E, O = A.E, A.O
    plan = A.registered(root)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    E.proof(root / 'learning', 'completion.json')
    end = E.read(root / 'train-control/exit.json')
    process = root / 'train-execution/pipeline-process-exit.json'
    assert end['status'] == 'train_complete' and end['exit_code'] == 0
    assert end['owned_exit_sha256'] == E.sha(process)
    assert E.read(process)['exit_code'] == 0 and E.read(process)['cleanup']['clean']
    assert end['completion_sha256'] == E.sha(root / 'learning/completion.json')
    source = Path(plan['value_source'])
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = A.Data(store, root / 'data', source / 'data', plan['input_columns'])
    all_held, folds, checkpoints, total_choices, maximum = [], [], 0, 0, 0.
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'
        fit = [f for f in store.families if O.T.fold(f['seed']) != fold]
        held = [f for f in store.families if O.T.fold(f['seed']) == fold]
        inner, valid = O.inner_partition(fit)
        roles = E.read(directory / 'roles.json'); old_roles = E.read(source / 'learning' / f'fold-{fold}/roles.json')
        for key, group in (('inner_train', inner), ('inner_validation', valid), ('fit', fit), ('held', held)):
            assert roles[key] == [f['seed'] for f in group] == old_roles[key]
        validation_ids = [i for i, row in enumerate(data.rows) if row['seed'] in roles['inner_validation']]
        curve = E.read(directory / 'stopping.json')
        assert [r['step'] for r in curve] == A.RECIPE['checkpoints']
        checked_curve = []
        warm_step = E.read(source / 'learning' / f'fold-{fold}/report.json')['selected_steps']
        warm = torch.load(source / 'learning' / f'fold-{fold}/inner-{warm_step}.pt', weights_only=True, map_location='cpu')
        for row in curve:
            weights = torch.load(directory / f'inner-{row["step"]}.pt', weights_only=True, map_location='cpu')
            if row['step'] == 0:
                assert all(torch.equal(v, warm[k]) for k, v in weights.items())
            got = summary(choices(weights, data, validation_ids, True, plan['input_columns']))
            same_summary(got, {k: v for k, v in row.items() if k != 'step'})
            checked_curve.append(dict(step=row['step'], **got)); checkpoints += 1
        best = sorted(checked_curve, key=lambda r: (-round(r['family_mean_gain'], 12), r['changed'], r['step']))[0]
        enabled = round(best['family_mean_gain'], 12) > 0
        selected = best['step'] if enabled else 0
        checkpoint = torch.load(directory / 'value.pt', weights_only=True, map_location='cpu')
        assert checkpoint['model_type'] == 'paired_afterstate_heart_value' and checkpoint['prediction_only']
        assert checkpoint['decision_enabled'] == enabled
        assert checkpoint['input_columns'] == plan['input_columns'] and checkpoint['feature_spec'] == store.spec
        assert checkpoint['provenance'] == dict(fold=fold, fit_families=roles['fit'], selected_steps=selected,
            value_sha256=E.sha(source / 'learning' / f'fold-{fold}/value.pt'), recipe=A.RECIPE)
        report = E.read(directory / 'report.json')
        assert report['selected_steps'] == selected and report['decision_enabled'] == enabled
        if selected == 0:
            original = torch.load(source / 'learning' / f'fold-{fold}/value.pt', weights_only=True, map_location='cpu')['model_state']
            assert all(torch.equal(v, original[k]) for k, v in checkpoint['model_state'].items())
        for name, families in (('fit', fit), ('held', held)):
            seeds = {f['seed'] for f in families}
            ids = [i for i, row in enumerate(data.rows) if row['seed'] in seeds]
            actual = choices(checkpoint['model_state'], data, ids, enabled, plan['input_columns'])
            expected = E.read(directory / f'{name}-choices.json')
            maximum = max(maximum, verify_choices(actual, expected)); total_choices += len(actual)
            same_summary(summary(actual), report[name])
            if name == 'held': all_held.extend(actual)
        folds.append(dict(fold=fold, selected_steps=selected, decision_enabled=enabled,
            held=report['held'], fit=report['fit']))
    overall = summary(all_held); initial = summary([r for r in all_held if r['initial']])
    values = np.array(list(overall['family_deltas'].values()))
    rng = np.random.default_rng(A.RECIPE['bootstrap_seed'])
    means = np.empty(A.RECIPE['bootstrap_draws'])
    for i in range(len(means)):
        means[i] = values[rng.integers(0, len(values), size=len(values))].mean()
    lower, upper = map(float, np.quantile(means, [.025, .975]))
    passed = lower > 0 and initial['chosen_wins'] > initial['parent_wins'] and all(round(r['held']['family_mean_gain'], 12) > 0 for r in folds)
    actual = E.read(root / 'learning/report.json')
    same_summary(overall, actual['all_states']); same_summary(initial, actual['initial'])
    np.testing.assert_allclose([lower, upper], actual['family_bootstrap_95'], atol=1e-12, rtol=0)
    assert passed == actual['learning_gate_passed']
    updates = 3*A.RECIPE['steps']+sum(r['selected_steps'] for r in folds)
    assert updates == actual['value_optimizer_updates']
    result = dict(status='complete_reviewed', experiment='E175', folds=folds,
        all_states=overall, initial=initial, family_bootstrap_95=[lower, upper], learning_gate_passed=passed,
        value_optimizer_updates=updates, independent_inner_checkpoints=checkpoints,
        independent_final_choices=total_choices, maximum_numpy_error=maximum,
        data_review_sha256=E.sha(root / 'data-review.json'), controller_exit_sha256=E.sha(root / 'train-control/exit.json'),
        learning_completion_sha256=E.sha(root / 'learning/completion.json'), reviewer_sha256=E.sha(__file__),
        new_games=0, policy_adoption=False,
        limits='Old-family conditional fixed-continuation decision screen; not natural or unseen policy performance.')
    E.write(root / 'training-review.json', result)
    print({k: v for k, v in result.items() if k not in ('folds', 'all_states', 'initial')}, flush=True)
    print({label: {k: v for k, v in result[label].items() if k != 'family_deltas'} for label in ('all_states', 'initial')}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
