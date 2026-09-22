"""Independent state-value stopping, fitted-only baseline and held score review."""
import argparse
from pathlib import Path
import sys

import numpy as np
import torch


def matrix(store, ids, columns):
    shared = store.shared.take(ids).to_dense().numpy()
    result = np.zeros((len(ids), store.spec['width']+store.spec['descriptor_dim']), dtype=np.float32)
    result[:, columns] = shared[:, columns]
    return result


def predict(weights, values):
    for layer in ('input', 'tail.1', 'tail.3'):
        values = values @ weights[layer+'.weight'].numpy().T+weights[layer+'.bias'].numpy()
        if layer != 'tail.3': values = values/(1+np.exp(np.clip(-values, -80, 80)))
    return (1/(1+np.exp(np.clip(-values[:, 0], -80, 80)))).astype(np.float64)


def table(data, families):
    ids = np.concatenate([np.arange(f['begin'], f['end']) for f in families])
    weights = np.concatenate([np.full(f['end']-f['begin'], 1./(f['end']-f['begin'])) for f in families])
    count = np.bincount(data.cells[ids], weights=weights, minlength=256)
    total = np.bincount(data.cells[ids], weights=weights*data.targets[ids], minlength=256)
    result = np.full(256, total.sum()/count.sum())
    np.divide(total, count, out=result, where=count > 0)
    return result


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_parent_state_value as V
    E, O = V.E, V.O
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    plan = V.registered(root)
    recipe = plan['recipe']
    E.proof(root / 'learning', 'completion.json')
    end = E.read(root / 'train-control/exit.json')
    process = root / 'train-execution/pipeline-process-exit.json'
    assert end['status'] == 'train_complete' and end['exit_code'] == 0
    assert end['owned_exit_sha256'] == E.sha(process)
    assert E.read(process)['exit_code'] == 0 and E.read(process)['cleanup']['clean']
    assert end['completion_sha256'] == E.sha(root / 'learning/completion.json')
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = V.Data(store, root / 'data', plan['input_columns'])
    results = []; maximum_error = 0.; checkpoint_count = 0
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'
        fit = [f for f in data.families if O.T.fold(f['seed']) != fold]
        held = [f for f in data.families if O.T.fold(f['seed']) == fold]
        inner, valid = O.inner_partition(fit)
        roles = E.read(directory / 'roles.json')
        for key, families in (('inner_train', inner), ('inner_validation', valid), ('fit', fit), ('held', held)):
            assert roles[key] == [f['seed'] for f in families]
        # Independent sampling arithmetic, including the actual owning family.
        rng = np.random.default_rng(recipe['seed']+2000+fold)
        indices = {}
        for key, families in (('validation_ids', valid), ('held_ids', held)):
            draws = rng.random((recipe['validation_draws'], 2))
            ids = []
            for a, b in draws:
                family = families[int(a*len(families))]
                ids.append(family['begin']+int(b*(family['end']-family['begin'])))
            assert ids == roles[key]
            indices[key] = np.array(ids)
        curve = E.read(directory / 'stopping.json')
        assert [r['step'] for r in curve] == recipe['checkpoints']
        weights = {r['step']: torch.load(directory / f'inner-{r["step"]}.pt', weights_only=True, map_location='cpu') for r in curve}
        initial = V.warm_model(Path(plan['encoder_source']), store.spec['width']+store.spec['descriptor_dim'], fold, True).state_dict()
        assert all(torch.equal(v, initial[k]) for k, v in weights[0].items())
        for state in weights.values():
            assert all(torch.equal(value, initial[key]) for key, value in state.items() if not key.startswith('tail.3.'))
        totals = {step: 0. for step in weights}
        ids = indices['validation_ids']
        for at in range(0, len(ids), 128):
            group = ids[at:at+128]
            features = matrix(store, group, plan['input_columns'])
            for step, weight in weights.items():
                totals[step] += float(np.sum((predict(weight, features)-data.targets[group])**2))
        for row in curve:
            error = abs(totals[row['step']]/len(ids)-row['brier'])
            assert error < 1e-6
            maximum_error = max(maximum_error, error); checkpoint_count += 1
        selected = min(curve, key=lambda r: (r['brier'], r['step']))['step']
        checkpoint = torch.load(directory / 'value.pt', weights_only=True, map_location='cpu')
        assert checkpoint['model_type'] == 'parent_heart_state_value' and checkpoint['prediction_only']
        assert checkpoint['input_columns'] == plan['input_columns'] and checkpoint['feature_spec'] == store.spec
        provenance = checkpoint['provenance']
        assert provenance['fold'] == fold and provenance['fit_families'] == roles['fit']
        assert provenance['selected_steps'] == selected and provenance['recipe'] == recipe
        assert provenance['encoder_frozen'] is True
        frozen = V.warm_model(Path(plan['encoder_source']), store.spec['width']+store.spec['descriptor_dim'], fold, False, True)
        assert sum(p.numel() for p in frozen.parameters() if p.requires_grad) == 65
        assert all(torch.equal(value, frozen.state_dict()[key]) for key, value in checkpoint['model_state'].items() if not key.startswith('tail.3.'))
        assert provenance['encoder_sha256'] == E.sha(Path(plan['encoder_source']) / 'learning' / f'fold-{fold}/auxiliary.pt')
        baseline, inner_baseline = table(data, fit), table(data, inner)
        np.testing.assert_allclose(baseline, np.load(directory / 'baseline.npy', allow_pickle=False), atol=1e-11)
        np.testing.assert_allclose(inner_baseline, np.load(directory / 'inner-baseline.npy', allow_pickle=False), atol=1e-11)
        held_ids = indices['held_ids']; total = 0.
        for at in range(0, len(held_ids), 128):
            group = held_ids[at:at+128]
            prediction = predict(checkpoint['model_state'], matrix(store, group, plan['input_columns']))
            total += float(np.sum((prediction-data.targets[group])**2))
        expected = dict(fold=fold, selected_steps=selected, held_brier=total/len(held_ids),
            baseline_brier=float(np.mean((baseline[data.cells[held_ids]]-data.targets[held_ids])**2)),
            inner_baseline_brier=float(np.mean((inner_baseline[data.cells[ids]]-data.targets[ids])**2)))
        report = E.read(directory / 'report.json')
        for key, value in expected.items():
            error = abs(report[key]-value)
            assert error < 1e-6
            maximum_error = max(maximum_error, error)
        results.append(expected); print(expected, flush=True)
    report = E.read(root / 'learning/report.json')
    neural = float(np.mean([r['held_brier'] for r in results]))
    reference = float(np.mean([r['baseline_brier'] for r in results]))
    passed = neural <= .9*reference and all(r['held_brier'] < r['baseline_brier'] for r in results)
    assert passed == report['prediction_gate_passed']
    assert abs(neural-report['held_brier']) < 1e-6 and abs(reference-report['baseline_brier']) < 1e-6
    updates = 3*recipe['steps']+sum(r['selected_steps'] for r in results)
    assert updates == report['value_optimizer_updates']
    assert report['encoder_frozen'] and report['trainable_parameters'] == 65
    result = dict(status='complete_reviewed', experiment='E172', folds=results, held_brier=neural,
        baseline_brier=reference, prediction_gate_passed=passed, value_optimizer_updates=updates,
        independent_inner_checkpoints=checkpoint_count, independent_held_predictions=3*recipe['validation_draws'],
        maximum_numpy_error=maximum_error, family_roles_and_fit_only_baselines_verified=True,
        all_inner_and_final_encoders_unchanged=True, trainable_parameters=65,
        data_review_sha256=E.sha(root / 'data-review.json'), controller_exit_sha256=E.sha(root / 'train-control/exit.json'),
        learning_completion_sha256=E.sha(root / 'learning/completion.json'), reviewer_sha256=E.sha(__file__),
        new_games=0, actor_optimizer_updates=0, auxiliary_optimizer_updates=0, policy_adoption=False,
        limits='State prediction under the frozen parent, not an action-selection model or natural/unseen policy win rate. All states remain grouped by the original family.')
    E.write(root / 'training-review.json', result)
    print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
