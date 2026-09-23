"""Independent stopping, value prediction and fixed-menu ranking review."""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_cost_relations_value as L
    E, O, V = L.E, L.O, L.V
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    plan = L.registered(root); E.proof(root/'learning', 'completion.json')
    spec = importlib.util.spec_from_file_location('value_check', root/'e170-review.py')
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    store = O.Store(Path(plan['learning_source'])/'store'); cost_shape = E.read(root/'layout.json'); facts = E.read(root/'card-facts.json')
    data = L.Data(store, root/'data', plan['input_columns'], cost_shape)
    feature_spec = importlib.util.spec_from_file_location('cost_check', root/'e187-check-features.py')
    feature_check = importlib.util.module_from_spec(feature_spec); feature_spec.loader.exec_module(feature_check)
    source = Path(plan['preceding_study']); encoder = Path(plan['encoder_source'])
    shape = data.layout; width = store.spec['width']+store.spec['descriptor_dim']; reports = []
    maximum_error = 0.; checkpoints = 0

    def matrix(ids):
        result = check.matrix(store, ids, plan['input_columns'])
        # Independent dense substitution, without the trainer's sparse rewrite.
        flags = data.flags[ids]; result[flags, shape['reward_column']] = 0.
        result[flags, shape['map_column']] = 1.
        return feature_check.matrix(result, cost_shape, facts)

    def score(weights, ids):
        return np.concatenate([check.predict(weights, matrix(ids[i:i+128])) for i in range(0, len(ids), 128)])

    for fold in range(3):
        directory = root/'learning'/f'fold-{fold}'
        roles = E.read(directory/'roles.json'); assert roles == E.read(source/'learning'/f'fold-{fold}/roles.json')
        fit = [f for f in data.families if O.T.fold(f['seed']) != fold]
        held = [f for f in data.families if O.T.fold(f['seed']) == fold]; inner, valid = O.inner_partition(fit)
        for role, families in (('fit', fit), ('held', held), ('inner_train', inner), ('inner_validation', valid)):
            assert roles[role] == [f['seed'] for f in families]
        rng = np.random.default_rng(plan['recipe']['seed']+2000+fold)
        for role, families in (('validation_ids', valid), ('held_ids', held)):
            ids = [families[int(a*len(families))]['begin'] + int(b*(families[int(a*len(families))]['end']-families[int(a*len(families))]['begin']))
                   for a, b in rng.random((8192, 2))]
            assert ids == roles[role]
        curve = E.read(directory/'stopping.json'); assert [r['step'] for r in curve] == plan['recipe']['checkpoints']
        validation_ids = np.array(roles['validation_ids']); held_ids = np.array(roles['held_ids'])
        weights = {r['step']: torch.load(directory/f'inner-{r["step"]}.pt', weights_only=True, map_location='cpu') for r in curve}
        initial = L.warm_model(encoder, width, fold, True).state_dict()
        assert all(torch.equal(value, weights[0][key]) for key, value in initial.items())
        totals = {step: 0. for step in weights}
        for at in range(0, len(validation_ids), 128):
            ids = validation_ids[at:at+128]; features = matrix(ids)
            actual, labels = data.batch(ids, set(roles['inner_validation']))
            np.testing.assert_allclose(actual.to_dense().numpy(), features, atol=2e-7, rtol=0)
            for step, values in weights.items():
                totals[step] += float(np.sum((check.predict(values, features)-data.targets[ids])**2))
        for row in curve:
            error = abs(totals[row['step']]/8192-row['brier']); assert error < 1e-6
            maximum_error = max(maximum_error, error); checkpoints += 1
        selected = min(curve, key=lambda row: (row['brier'], row['step']))['step']
        cp = torch.load(directory/'value.pt', weights_only=True, map_location='cpu')
        assert cp['model_type'] == L.MODEL_TYPE and cp['normalization'] == L.L.VERSION and cp['prediction_only']
        assert cp['provenance']['fit_families'] == roles['fit'] and cp['provenance']['selected_steps'] == selected
        assert cp['provenance']['recipe'] == plan['recipe'] and cp['input_columns'] == plan['input_columns']
        assert cp['cost_layout'] == cost_shape and cp['card_facts_sha256'] == E.sha(root/'card-facts.json')
        assert cp['paired_width'] == width+L.WIDTH
        actual = E.read(directory/'report.json'); assert actual['selected_steps'] == selected
        error = float(np.mean((score(cp['model_state'], held_ids)-data.targets[held_ids])**2))
        assert abs(error-actual['held_brier']) < 1e-6
        table = check.table(data, fit)
        np.testing.assert_allclose(table, np.load(directory/'baseline.npy'), atol=1e-12, rtol=0)
        np.testing.assert_array_equal(np.load(directory/'baseline.npy'), np.load(source/'learning'/f'fold-{fold}/baseline.npy'))
        assert abs(float(np.mean((table[data.cells[held_ids]]-data.targets[held_ids])**2))-actual['baseline_brier']) < 1e-12
        reports.append(actual)
    report = E.read(root/'learning/report.json'); assert report['folds'] == reports
    assert report['value_optimizer_updates'] == 60000+sum(r['selected_steps'] for r in reports)
    gate = all(r['held_brier'] < r['baseline_brier'] for r in reports) and np.mean([r['held_brier'] for r in reports]) <= .9*np.mean([r['baseline_brier'] for r in reports])
    assert gate == report['prediction_gate_passed']

    # The same fixed 6264 existing menus diagnose action utility. All source
    # families are excluded from their scoring model's fitting partition.
    rows = E.read(Path(plan['mechanism_evidence'])/'choices.json'); choices = []
    for fold in range(3):
        cp = torch.load(root/'learning'/f'fold-{fold}/value.pt', weights_only=True, map_location='cpu')
        selected = [r for r in rows if r['fold'] == fold]
        assert all(r['seed'] not in cp['provenance']['fit_families'] for r in selected)
        ids = np.array(sorted({s for r in selected for s in r['successors']}))
        predictions = dict(zip(map(int, ids), score(cp['model_state'], ids).tolist()))
        model = L.warm_model(encoder, width, fold, False); model.load_state_dict(cp['model_state']); model.eval()
        native_predictions = {}
        with torch.inference_mode():
            for start in range(0, len(ids), 128):
                batch = ids[start:start+128]; features, _ = data.batch(batch, set(E.read(root/'learning'/f'fold-{fold}/roles.json')['held']))
                values = model(features).squeeze(-1).sigmoid().tolist()
                native_predictions.update(zip(map(int, batch), values))
        np.testing.assert_allclose([native_predictions[int(i)] for i in ids], [predictions[int(i)] for i in ids], atol=1e-6, rtol=0)
        for row in selected:
            scores = [predictions[s] for s in row['successors']]; parent = row['parent']
            best = max(range(len(scores)), key=lambda i: (scores[i], i == parent, -i))
            chosen = parent if scores[best]-scores[parent] <= 1e-6 else best
            actual_scores = [native_predictions[s] for s in row['successors']]
            native_best = max(range(len(actual_scores)), key=lambda i: (actual_scores[i], i == parent, -i))
            native_chosen = parent if actual_scores[native_best]-actual_scores[parent] <= 1e-6 else native_best
            assert native_chosen == chosen, 'NumPy and Torch rankings differ'
            labels = data.targets[row['successors']].astype(int).tolist(); assert labels == row['labels']
            choices.append(dict(seed=row['seed'], state=row['state'], fold=fold, act=row['act'], floor=row['floor'],
                                parent=parent, chosen=chosen, labels=labels, scores=scores))
    def summarize(selected):
        result = Counter(states=len(selected))
        for row in selected:
            old, new = row['labels'][row['parent']], row['labels'][row['chosen']]
            result.update(parent=old, candidate=new, gained=int(new > old), lost=int(new < old), changed=int(row['parent'] != row['chosen']))
        return dict(result)
    first = [r for r in choices if r['act'] == r['floor'] == 1]; first_summary = summarize(first)
    assert len(first) == 1536 and first_summary['parent'] == 149
    x = O.C.D.runtime(plan['runtime'])
    paired = x.B.paired_counts([r['labels'][r['parent']] for r in first], [r['labels'][r['chosen']] for r in first])
    by_fold = {str(f): summarize([r for r in first if r['fold'] == f]) for f in range(3)}
    action_gate = paired['net_gain'] >= 20 and paired['exact_p'] < .05 and all(r['candidate'] >= r['parent'] for r in by_fold.values())
    owned = E.read(root/'train-execution/pipeline-process-exit.json'); end = E.read(root/'control/exit.json')
    assert end['status'] == 'complete' and end['exit_code'] == owned['exit_code'] == 0 and owned['cleanup']['clean']
    assert end['owned_exit_sha256'] == E.sha(root/'train-execution/pipeline-process-exit.json')
    assert end['completion_sha256'] == E.sha(root/'learning/completion.json')
    E.write(root/'ranking-choices.json', choices)
    result = dict(status='complete_reviewed', experiment=plan['experiment'], result=report, inner_checkpoints_verified=checkpoints,
        held_predictions_verified=24576, maximum_brier_error=maximum_error, initial=first_summary,
        initial_paired=paired, initial_by_fold=by_fold, all_recorded_menus=summarize(choices),
        action_gate_passed=bool(action_gate), eligible_for_policy_design=bool(gate and action_gate),
        process_cleanup_verified=True, torch_numpy_menu_choices_verified=len(choices), learning_completion_sha256=E.sha(root/'learning/completion.json'),
        ranking_choices_sha256=E.sha(root/'ranking-choices.json'), reviewer_sha256=E.sha(__file__),
        new_games=0, policy_adoption=False, unused_acceptance_games=0)
    E.write(root/'training-review.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', required=True, type=Path)
    main(parser.parse_args().study.resolve())
