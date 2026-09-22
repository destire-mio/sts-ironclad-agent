"""NumPy review of auxiliary stopping, family roles and the prediction gate."""
import argparse
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_combat_pretraining as P
    O, E, I = P.O, P.E, P.I
    plan = P.registered(root)
    torch.set_num_threads(1)
    E.proof(root / 'learning', 'completion.json')
    end = E.read(root / 'train-control/exit.json')
    assert end['status'] == 'train_complete' and end['exit_code'] == 0
    process = root / 'train-execution/pipeline-process-exit.json'
    assert E.sha(process) == end['owned_exit_sha256']
    assert E.read(process)['exit_code'] == 0 and E.read(process)['cleanup']['clean']
    spec = importlib.util.spec_from_file_location('heart_review', Path(__file__).with_name('e164-heart-review.py'))
    H = importlib.util.module_from_spec(spec); spec.loader.exec_module(H)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = P.Data(store, root / 'data')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    examples = I.Examples(store, exact['observed_best'])
    maximum_error, checkpoint_count = 0., 0
    records, selected_steps = [], []
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'
        roles = E.read(directory / 'auxiliary-roles.json')
        fit = [f for f in examples.families if O.T.fold(f['seed']) != fold]
        inner, valid = O.inner_partition(fit)
        assert roles['inner_train'] == [f['seed'] for f in inner]
        assert roles['inner_validation'] == [f['seed'] for f in valid]
        assert roles['fit'] == [f['seed'] for f in fit]
        held_seeds = {f['seed'] for f in examples.families if O.T.fold(f['seed']) == fold}
        assert set(roles['held']) == held_seeds and not set(roles['fit']) & held_seeds
        def select(families, uniforms):
            return np.array([f['indices'][min(int(u[1] * len(f['indices'])), len(f['indices']) - 1)]
                for u in uniforms for f in [families[min(int(u[0] * len(families)), len(families) - 1)]]])
        a_valid = [f for f in data.families if f['seed'] in set(roles['inner_validation'])]
        a_held = [f for f in data.families if f['seed'] in held_seeds]
        rng = np.random.default_rng(P.RECIPE['seed'] + 2000 + fold)
        ids = select(a_valid, rng.random((P.RECIPE['validation_draws'], 2)))
        held = select(a_held, rng.random((P.RECIPE['validation_draws'], 2)))
        assert ids.tolist() == roles['validation_ids'] and held.tolist() == roles['held_ids']
        curve = E.read(directory / 'auxiliary-stopping.json')
        assert [r['step'] for r in curve] == P.RECIPE['checkpoints']
        weights = {r['step']: torch.load(directory / f'aux-inner-{r["step"]}.pt', weights_only=True, map_location='cpu') for r in curve}
        initial = P.auxiliary_model(store.spec['width'] + store.spec['descriptor_dim'], fold).state_dict()
        assert all(torch.equal(v, initial[k]) for k, v in weights[0].items())
        sums = {step: np.zeros(2) for step in weights}
        for at in range(0, len(ids), 128):
            selected = ids[at:at+128]; edges = data.edges[selected]
            features = H.matrix(store, store.edge_state[edges], store.edge_action[edges])
            for step, w in weights.items():
                sums[step] += ((H.logits(w, features).astype(np.float64) - data.targets[selected]) ** 2).sum(axis=0)
        for row in curve:
            expected = sums[row['step']] / len(ids)
            err = float(np.max(np.abs(expected - row['mse'])))
            maximum_error = max(maximum_error, err)
            assert err < 1e-5 and abs(float(expected.mean()) - row['loss']) < 1e-5
            checkpoint_count += 1
        selected = min(curve, key=lambda r: (r['loss'], r['step']))['step']
        selected_steps.append(selected)
        final = torch.load(directory / 'auxiliary.pt', weights_only=True, map_location='cpu')
        sum_error = np.zeros(2)
        for at in range(0, len(held), 128):
            selected_ids = held[at:at+128]; edges = data.edges[selected_ids]
            features = H.matrix(store, store.edge_state[edges], store.edge_action[edges])
            sum_error += ((H.logits(final, features).astype(np.float64) - data.targets[selected_ids]) ** 2).sum(axis=0)
        def baseline_loss(family_seeds, sample):
            weights_by_cell = np.zeros(140); sums_by_cell = np.zeros((140, 2))
            for family in data.families:
                if family['seed'] not in family_seeds:
                    continue
                rows = family['indices']
                for cell in np.unique(data.cells[rows]):
                    subset = rows[data.cells[rows] == cell]
                    weights_by_cell[cell] += len(subset) / len(rows)
                    sums_by_cell[cell] += data.targets[subset].astype(np.float64).sum(axis=0) / len(rows)
            global_mean = sums_by_cell.sum(axis=0) / weights_by_cell.sum()
            prediction = np.array([sums_by_cell[c] / weights_by_cell[c] if weights_by_cell[c] else global_mean for c in data.cells[sample]])
            return ((prediction - data.targets[sample]) ** 2).mean(axis=0)
        result = E.read(directory / 'auxiliary-report.json')
        np.testing.assert_allclose(result['held_mse'], sum_error / len(held), atol=1e-5)
        np.testing.assert_allclose(result['held_baseline_mse'], baseline_loss(set(roles['fit']), held), atol=1e-6)
        np.testing.assert_allclose(result['inner_baseline_mse'], baseline_loss(set(roles['inner_train']), ids), atol=1e-6)
        assert result['selected_steps'] == selected
        records.append(result)
    neural = float(np.mean([r['held_mse'] for r in records]))
    baseline = float(np.mean([r['held_baseline_mse'] for r in records]))
    passed = neural <= P.RECIPE['auxiliary_relative_mse_gate'] * baseline and all(np.mean(r['held_mse']) < np.mean(r['held_baseline_mse']) for r in records)
    screen = E.read(root / 'learning/auxiliary-screen.json')
    assert screen == dict(folds=records, mse=neural, baseline_mse=baseline, passed=passed)
    report = E.read(root / 'learning/report.json')
    updates = 3 * P.RECIPE['steps'] + sum(selected_steps)
    assert report['auxiliary_passed'] == passed and report['auxiliary_optimizer_steps'] == updates
    auxiliary = dict(status='complete_reviewed', passed=passed, selected_steps=selected_steps, optimizer_steps=updates,
        inner_checkpoints=checkpoint_count, maximum_numpy_error=maximum_error, held_mse=neural,
        held_baseline_mse=baseline, learning_completion_sha256=E.sha(root / 'learning/completion.json'), reviewer_sha256=E.sha(__file__))
    E.write(root / 'auxiliary-review.json', auxiliary)
    if passed:
        H.main(root)
    else:
        assert report['models'] == [] and report['heart_optimizer_steps'] == 0 and not report['eligible_for_natural_evaluation']
        assert not any((root / 'learning').glob('*/candidate.pt'))
        E.write(root / 'training-review.json', dict(status='complete_reviewed', experiment='E164', auxiliary=auxiliary,
            eligible_for_natural_evaluation=False, heart_optimizer_steps=0,
            learning_completion_sha256=E.sha(root / 'learning/completion.json'),
            controller_exit_sha256=E.sha(root / 'train-control/exit.json'), reviewer_sha256=E.sha(__file__),
            new_training_rollouts=0, natural_games=0, production_adoption=False))
    print(auxiliary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
