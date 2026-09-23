"""Review the fixed direct-combat subset, original fitting recipe and controls."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import torch


def main(root, phase):
    sys.path.insert(0, str(root / 'program'))
    import heart_direct_combat_delta as F
    D, E, O = F.D, F.E, F.O
    plan = F.registered(root)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = F.Data(store, plan)
    source = Path(plan['value_source']); old = Path(plan['comparison'])
    spec = importlib.util.spec_from_file_location('e178_review', root / 'e178-review.py')
    V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
    audit = E.read(Path(plan['path_audit']) / 'audit/pairs.json')
    eligible = [i for i, r in enumerate(audit) if r['covered'] and r['both_transparent']]
    assert eligible == sorted(i for group in data.menu_pairs.values() for i in group)
    per_menu = {}
    for i in eligible:
        row, candidate = data.pairs[i]
        per_menu.setdefault(int(row), []).append(i)
    per_seed = {}
    for row in sorted(per_menu): per_seed.setdefault(data.rows[row]['seed'], []).append(row)

    def sample(families, uniforms):
        available = [f['seed'] for f in families if f['seed'] in per_seed]
        ids = []
        for a, b, c in uniforms:
            seed = available[int(a*len(available))]
            menus = per_seed[seed]; candidates = per_menu[menus[int(b*len(menus))]]
            ids.append(candidates[int(c*len(candidates))])
        return ids

    if phase == 'data':
        targets = E.read(Path(plan['target_source']) / 'data/pairs.json')
        for at in range(0, len(eligible), 128):
            group = eligible[at:at+128]
            _, values = V.ids_and_targets(data, group)
            np.testing.assert_allclose(values, [targets[i]['combat_difference'] for i in group], atol=1e-7, rtol=0)
        full = D.Data(store, plan)
        groups = np.array(eligible[::max(1, len(eligible)//128)][:128])
        allowed = set(per_seed)
        actual, labels = data.batch(groups, allowed)
        expected, original_labels = full.batch(groups, allowed)
        assert torch.equal(actual.indices(), expected.indices()) and torch.equal(actual.values(), expected.values())
        assert torch.equal(labels, original_labels)
        maximum = 0.; rejected = 0; coverage = []
        for fold in range(3):
            fits = [f for f in store.families if O.T.fold(f['seed']) != fold]
            held = [f for f in store.families if O.T.fold(f['seed']) == fold]
            inner, valid = O.inner_partition(fits)
            role = dict(inner_train=inner, inner_validation=valid, fit=fits, held=held)
            coverage.append(dict(fold=fold, **{k: sum(f['seed'] in per_seed for f in fs) for k, fs in role.items()}))
            for fs in role.values():
                draws = np.random.default_rng(2026092378+fold).random((128, 3))
                assert data.sample(fs, draws).tolist() == sample(fs, draws)
            for nested in (True, False):
                model, retained = D.warm_model(source, store.spec['width']+store.spec['descriptor_dim'], fold, nested)
                original = D.A.warm_model(source, store.spec['width']+store.spec['descriptor_dim'], fold, nested).state_dict()
                assert all(torch.equal(value, original[key]) for key, value in model.state_dict().items() if not key.startswith('tail.3.'))
                assert all(torch.count_nonzero(value) == 0 for value in model.tail[-1].state_dict().values())
                assert torch.equal(retained['weight'], original['tail.3.weight']) and torch.equal(retained['bias'], original['tail.3.bias'])
            candidate = next(i for i in eligible if data.rows[data.pairs[i][0]]['seed'] in {f['seed'] for f in held})
            try:
                data.batch(np.array([candidate]), {f['seed'] for f in inner})
                raise AssertionError('held target admitted')
            except ValueError as exc:
                assert 'held family' in str(exc); rejected += 1
        forbidden = next(i for i, p in enumerate(audit) if p['covered'] and not p['both_transparent'])
        try:
            data.batch(np.array([forbidden]), {f['seed'] for f in store.families})
            raise AssertionError('mixed path admitted')
        except ValueError as exc:
            assert 'intervening-combat pair' in str(exc); rejected += 1
        # Query a nonzero old model; no optimizer step is needed to test the
        # unchanged input path and new subset restrictions.
        saved = torch.load(old / 'learning/fold-1/auxiliary.pt', weights_only=True, map_location='cpu')
        model, _ = D.warm_model(source, store.spec['width']+store.spec['descriptor_dim'], 1, False)
        model.load_state_dict(saved['model_state'])
        with torch.inference_mode(): pred = D.differences(model(actual)).numpy()
        ids, _ = V.ids_and_targets(data, groups)
        independent = V.predict(saved['model_state'], V.matrix(store, ids, plan['input_columns']))
        np.testing.assert_allclose(pred, independent, atol=1e-6, rtol=0)
        maximum = float(np.abs(pred-independent).max())
        result = dict(status='complete_reviewed', experiment='E190', scope=data.coverage, role_coverage=coverage,
            targets_verified=len(eligible), unchanged_input_pairs=len(groups), warm_models_verified=6,
            forbidden_target_rejections=rejected, maximum_numpy_error=maximum,
            optimizer_updates=0, new_games=0, target_completion_sha256=E.sha(Path(plan['target_source']) / 'data/completion.json'),
            path_review_sha256=E.sha(Path(plan['path_audit']) / 'review.json'), reviewer_sha256=E.sha(__file__))
        E.write(root / 'data-review.json', result); print(json.dumps(result), flush=True); return

    E.proof(root / 'learning', 'completion.json')
    end = E.read(root / 'train-control/exit.json')
    process = root / 'train-execution/pipeline-process-exit.json'
    assert end['status'] == 'train_complete' and end['exit_code'] == 0
    assert end['owned_exit_sha256'] == E.sha(process) and end['completion_sha256'] == E.sha(root / 'learning/completion.json')
    assert E.read(process)['exit_code'] == 0 and E.read(process)['cleanup']['clean']
    reports = []; checkpoint_count = 0; maximum = 0.
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'
        roles = E.read(directory / 'roles.json')
        original = E.read(source / 'learning' / f'fold-{fold}/roles.json')
        for key in ('inner_train', 'inner_validation', 'fit', 'held'):
            assert roles[key] == original[key]
            assert roles['auxiliary_families'][key] == [s for s in original[key] if s in per_seed]
        rng = np.random.default_rng(D.RECIPE['seed']+2000+fold)
        for key, role in [('validation_pairs', 'inner_validation'), ('held_pairs', 'held')]:
            fs = [f for f in store.families if f['seed'] in roles[role]]
            assert roles[key] == sample(fs, rng.random((D.RECIPE['validation_draws'], 3)))
        curve = E.read(directory / 'stopping.json')
        assert [p['step'] for p in curve] == D.RECIPE['checkpoints']
        values = []
        for point in curve:
            weights = torch.load(directory / f'inner-{point["step"]}.pt', weights_only=True, map_location='cpu')
            if point['step'] == 0:
                warm, _ = D.warm_model(source, store.spec['width']+store.spec['descriptor_dim'], fold, True)
                assert all(torch.equal(warm.state_dict()[k], v) for k, v in weights.items())
            error, base = V.errors(weights, data, roles['validation_pairs'], plan['input_columns'])
            np.testing.assert_allclose(error, point['mse'], atol=1e-7, rtol=0)
            np.testing.assert_allclose(base, point['zero_baseline_mse'], atol=1e-7, rtol=0)
            maximum = max(maximum, float(np.abs(error-point['mse']).max()))
            values.append((float(error.mean()), point['step'])); checkpoint_count += 1
        selected = min(values)[1]
        saved = torch.load(directory / 'auxiliary.pt', weights_only=True, map_location='cpu')
        assert saved['provenance']['selected_steps'] == selected and saved['provenance']['fit_families'] == roles['fit']
        assert saved['provenance']['recipe'] == D.RECIPE and saved['input_columns'] == plan['input_columns']
        _, retained = D.warm_model(source, store.spec['width']+store.spec['descriptor_dim'], fold, False)
        assert all(torch.equal(v, retained[k]) for k, v in saved['retained_heart_head'].items())
        error, base = V.errors(saved['model_state'], data, roles['held_pairs'], plan['input_columns'])
        recorded = E.read(directory / 'report.json')
        np.testing.assert_allclose(error, recorded['held_mse'], atol=1e-7, rtol=0)
        np.testing.assert_allclose(base, recorded['zero_baseline_mse'], atol=1e-7, rtol=0)
        previous = torch.load(old / 'learning' / f'fold-{fold}/auxiliary.pt', weights_only=True, map_location='cpu')
        control_error, control_base = V.errors(previous['model_state'], data, roles['held_pairs'], plan['input_columns'])
        np.testing.assert_array_equal(base, control_base)
        reports.append(dict(fold=fold, selected_steps=selected, candidate_mse=error.tolist(), zero_mse=base.tolist(), old_all_pair_model_mse=control_error.tolist()))
    candidate = float(np.mean([r['candidate_mse'] for r in reports]))
    zero = float(np.mean([r['zero_mse'] for r in reports]))
    control = float(np.mean([r['old_all_pair_model_mse'] for r in reports]))
    passed = candidate <= .9*zero and candidate <= .9*control and all(np.mean(r['candidate_mse']) < min(np.mean(r['zero_mse']), np.mean(r['old_all_pair_model_mse'])) for r in reports)
    summary = E.read(root / 'learning/report.json')
    np.testing.assert_allclose(summary['held_mse'], candidate, atol=1e-7, rtol=0)
    assert summary['auxiliary_optimizer_updates'] == 15000+sum(r['selected_steps'] for r in reports)
    result = dict(status='complete_reviewed', experiment='E190', folds=reports, held_mse=candidate,
        zero_mse=zero, old_all_pair_model_mse=control, matched_auxiliary_gate_passed=bool(passed),
        auxiliary_optimizer_updates=summary['auxiliary_optimizer_updates'], scope=data.coverage,
        inner_checkpoints_verified=checkpoint_count, held_predictions_verified=24576,
        maximum_numpy_error=maximum, learning_completion_sha256=E.sha(root / 'learning/completion.json'),
        reviewer_sha256=E.sha(__file__), controller_exit_sha256=E.sha(root / 'train-control/exit.json'),
        new_games=0, policy_adoption=False, unused_acceptance_games=0,
        limits=plan['result_limits'])
    E.write(root / 'training-review.json', result); print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--phase', choices=('data', 'training'), required=True)
    args = parser.parse_args()
    main(args.study.resolve(), args.phase)
