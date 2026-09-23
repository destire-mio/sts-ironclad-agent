"""Fit a 64-weight card-effect correction on reserved historical families.

The E185/E187 inner neural checkpoints stay frozen. Their gradient-training
families, correction-fitting families and outer evaluation families differ.
The correction group previously selected neural stopping steps; it is not a
new or entirely untouched set. Only historical development is measured here.
"""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def hidden_and_probability(weights, inputs):
    """Canonical float64 inference, identical numerical path for both arms."""
    def silu(v): return v/(1+np.exp(np.clip(-v, -80, 80)))
    h = silu(inputs.astype(np.float64)@weights['input.weight'].T+weights['input.bias'])
    h = silu(h@weights['tail.1.weight'].T+weights['tail.1.bias'])
    logits = (h@weights['tail.3.weight'].T+weights['tail.3.bias'])[:, 0]
    return h, 1/(1+np.exp(np.clip(-logits, -80, 80)))


def ridge_correction(difference, residual, weight, strength=1., scale_floor=.01):
    assert difference.ndim == 2 and difference.shape[1] == 64
    assert len(difference) == len(residual) == len(weight) and len(weight)
    assert np.isfinite(difference).all() and np.isfinite(residual).all()
    assert np.isfinite(weight).all() and (weight > 0).all() and strength > 0
    scale = np.maximum(np.sqrt(np.average(difference**2, weights=weight, axis=0)), scale_floor)
    z = difference/scale
    normal = z.T@(z*weight[:, None])+strength*np.eye(64)
    rhs = z.T@(weight*residual)
    coefficient = np.linalg.solve(normal, rhs)
    error = float(np.max(np.abs(normal@coefficient-rhs)))
    assert error < 1e-9 and np.isfinite(coefficient).all()
    return coefficient, scale, error


def differences(hidden, probability, parent):
    return hidden-hidden[parent], probability-probability[parent]


def choose(scores, parent, margin=1e-6):
    best = max(range(len(scores)), key=lambda i: (float(scores[i]), i == parent, -i))
    return parent if scores[best] <= margin else best


def objective_checks():
    # A 20%-successful alternative to a never-successful parent has positive
    # expected improvement, even though eight of ten observed results tie.
    x = np.zeros((10, 64)); x[:, 0] = 1.
    y = np.r_[np.ones(2), np.zeros(8)]; w = np.full(10, .1)
    beta, scale, _ = ridge_correction(x, y, w)
    assert np.isclose(beta[0], .1) and choose([0., float((x[0]/scale)@beta)], 0) == 1
    reverse, reverse_scale, _ = ridge_correction(-x, -y, w)
    np.testing.assert_allclose(beta, reverse, atol=1e-12)
    np.testing.assert_array_equal(scale, reverse_scale)
    zero, _, _ = ridge_correction(x, np.zeros(10), w)
    assert np.count_nonzero(zero) == 0
    repeated, repeated_scale, _ = ridge_correction(np.repeat(x, 2, axis=0), np.repeat(y, 2), np.repeat(w/2, 2))
    np.testing.assert_allclose(beta, repeated, atol=1e-12)
    np.testing.assert_allclose(scale, repeated_scale, atol=1e-15, rtol=0)
    assert choose([0., 1e-7], 0) == 0 and choose([0., 0.], 0) == 0
    return 5


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def main(root):
    plan = __import__('json').loads((root/'protocol.json').read_text())
    sys.path.insert(0, str(Path(plan['cost_source'])/'program'))
    import heart_cost_relations_value as L
    E, O = L.E, L.O
    registration = E.read(root/'registration.json')
    assert registration['runner_sha256'] == E.sha(__file__)
    for path, digest in registration['hashes'].items(): assert E.sha(path) == digest, path
    assert plan['ridge_strength'] == 1. and plan['scale_floor'] == .01 and plan['parent_margin'] == 1e-6
    assert plan['new_games'] == plan['neural_optimizer_updates'] == 0
    checks = objective_checks()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    cost_root = Path(plan['cost_source']); base_root = Path(plan['base_source'])
    cost_plan = L.registered(cost_root)
    assert E.read(cost_root/'training-review.json')['result']['prediction_gate_passed']
    assert not E.read(cost_root/'training-review.json')['action_gate_passed']
    for source in (base_root, cost_root):
        E.proof(source/'learning', 'completion.json')
        assert E.read(source/'training-review.json')['learning_completion_sha256'] == E.sha(source/'learning/completion.json')
    pair_root = Path(plan['paired_source']); E.proof(pair_root/'data', 'completion.json')
    rows = E.read(pair_root/'data/rows.json'); assert len(rows) == 6264
    store = O.Store(Path(cost_plan['learning_source'])/'store')
    data = L.L.Data(store, base_root/'data', cost_plan['input_columns'])
    facts, shape = E.read(cost_root/'card-facts.json'), E.read(cost_root/'layout.json')
    cost_check = load_module('cost_check', cost_root/'e187-check-features.py')
    families = {f['seed']: f for f in data.families}
    for row in rows:
        family = families[row['seed']]
        assert family['begin'] <= row['state'] < family['end']
        assert all(family['begin'] <= s < family['end'] for s in row['successors'])
    state_ids = np.array(sorted({s for row in rows for s in row['successors']}), dtype=np.int64)
    lookup = {int(state): i for i, state in enumerate(state_ids)}
    out = root/'learning'; out.mkdir(); cache = {}; heads = []
    for arm, source in (('base', base_root), ('cost', cost_root)):
        for fold in range(3):
            roles = E.read(source/'learning'/f'fold-{fold}/roles.json')
            assert roles == E.read(base_root/'learning'/f'fold-{fold}/roles.json')
            neural, calibration, held = (set(roles[k]) for k in ('inner_train', 'inner_validation', 'held'))
            assert not neural & calibration and not neural & held and not calibration & held
            assert neural | calibration | held == set(families)
            assert neural | calibration == set(roles['fit'])
            stopped = E.read(source/'learning'/f'fold-{fold}/stopping.json')
            step = min(stopped, key=lambda r: (r['brier'], r['step']))['step']
            checkpoint = source/'learning'/f'fold-{fold}'/f'inner-{step}.pt'
            weights = {k: v.numpy().astype(np.float64) for k, v in torch.load(checkpoint, weights_only=True, map_location='cpu').items()}
            hidden, probability = [], []
            for start in range(0, len(state_ids), 128):
                ids = state_ids[start:start+128]
                base = L.V.state_features(store, ids, cost_plan['input_columns'])
                base = L.L.normalize(base, data.flags[ids], data.layout['reward_column'], data.layout['map_column'])
                features = base.to_dense().numpy()
                if arm == 'cost': features = cost_check.matrix(features, shape, facts)
                h, p = hidden_and_probability(weights, features)
                hidden.append(h); probability.append(p)
            hidden, probability = np.concatenate(hidden), np.concatenate(probability)
            cache[arm, fold] = (hidden, probability)
            selected = [row for row in rows if row['seed'] in calibration]
            menus_per_family = Counter(row['seed'] for row in selected)
            assert set(menus_per_family) == calibration
            dx, residual, pair_weights, owners = [], [], [], []
            for row in selected:
                assert row['seed'] not in neural | held
                ids = [lookup[s] for s in row['successors']]
                d, base_delta = differences(hidden[ids], probability[ids], row['parent'])
                labels = data.targets[row['successors']]
                for i in range(len(ids)):
                    if i == row['parent']: continue
                    dx.append(d[i]); residual.append(float(labels[i])-float(labels[row['parent']])-base_delta[i])
                    pair_weights.append(1/(menus_per_family[row['seed']]*(len(ids)-1))); owners.append(row['seed'])
            dx, residual, pair_weights = np.array(dx), np.array(residual), np.array(pair_weights)
            owners = np.array(owners, dtype=np.int64)
            for seed in calibration: assert np.isclose(pair_weights[owners == seed].sum(), 1., rtol=0, atol=1e-12)
            beta, scale, error = ridge_correction(dx, residual, pair_weights, plan['ridge_strength'], plan['scale_floor'])
            head = dict(arm=arm, fold=fold, neural_source=str(checkpoint), neural_sha256=E.sha(checkpoint),
                selected_neural_steps=step, neural_gradient_families=sorted(neural), calibration_families=sorted(calibration),
                outer_families=sorted(held), weights=beta.tolist(), scale=scale.tolist(),
                fitting_pairs=len(dx), fitting_menus=len(selected), fitted_coefficients=64,
                ridge_strength=plan['ridge_strength'], scale_floor=plan['scale_floor'],
                normal_equation_maximum_residual=error,
                fitting_residual_mse_before=float(np.average(residual**2, weights=pair_weights)),
                fitting_residual_mse_after=float(np.average((residual-(dx/scale)@beta)**2, weights=pair_weights)),
                role_note='Calibration labels selected the original neural stopping step but never entered its gradient updates. Outer families are historical development, not untouched acceptance.')
            E.write(out/f'{arm}-fold-{fold}.json', head); heads.append(head)
            print(dict(stage='fit', arm=arm, fold=fold, calibration_families=len(calibration), pairs=len(dx)), flush=True)
    # Freeze all six fitted heads before reading outer card outcomes.
    E.write(out/'heads-complete.json', dict(status='complete', hashes={p.name: E.sha(p) for p in out.glob('*-fold-*.json')}))
    records = []; summaries = {}
    for head in heads:
        arm, fold = head['arm'], head['fold']; hidden, probability = cache[arm, fold]
        beta, scale = np.array(head['weights']), np.array(head['scale'])
        held = set(head['outer_families'])
        for row in rows:
            if row['seed'] not in held: continue
            assert row['seed'] not in head['neural_gradient_families'] and row['seed'] not in head['calibration_families']
            ids = [lookup[s] for s in row['successors']]
            delta, base_delta = differences(hidden[ids], probability[ids], row['parent'])
            scores = base_delta+(delta/scale)@beta
            chosen, uncorrected = choose(scores, row['parent']), choose(base_delta, row['parent'])
            labels = data.targets[row['successors']].astype(int).tolist()
            records.append(dict(arm=arm, fold=fold, seed=row['seed'], state=row['state'], act=row['act'], floor=row['floor'],
                parent=row['parent'], uncorrected=uncorrected, chosen=chosen, labels=labels,
                scores=scores.tolist(), uncorrected_scores=base_delta.tolist()))
    def summarize(subset):
        c = Counter(states=len(subset))
        for r in subset:
            parent, old, new = (r['labels'][r[k]] for k in ('parent', 'uncorrected', 'chosen'))
            c.update(parent=parent, uncorrected=old, candidate=new, gained=int(new > parent), lost=int(new < parent),
                gained_vs_uncorrected=int(new > old), lost_vs_uncorrected=int(new < old), changed=int(r['chosen'] != r['parent']))
        return dict(c)
    x = O.C.D.runtime(cost_plan['runtime'])
    for arm in ('base', 'cost'):
        arm_rows = [r for r in records if r['arm'] == arm]
        first = [r for r in arm_rows if r['act'] == r['floor'] == 1]
        assert len(arm_rows) == 6264 and len(first) == len({r['seed'] for r in first}) == 1536
        paired = x.B.paired_counts([r['labels'][r['parent']] for r in first], [r['labels'][r['chosen']] for r in first])
        assert paired['baseline_wins'] == 149
        folds = {str(f): summarize([r for r in first if r['fold'] == f]) for f in range(3)}
        passed = paired['net_gain'] >= 20 and paired['exact_p'] < .05 and all(r['candidate'] >= r['parent'] for r in folds.values())
        summaries[arm] = dict(initial=summarize(first), initial_paired=paired, initial_by_fold=folds,
            all_recorded_menus=summarize(arm_rows), action_gate_passed=bool(passed))
    cost_first = {r['seed']: r for r in records if r['arm'] == 'cost' and r['act'] == r['floor'] == 1}
    base_first = {r['seed']: r for r in records if r['arm'] == 'base' and r['act'] == r['floor'] == 1}
    ordered = sorted(cost_first)
    matched = x.B.paired_counts([base_first[s]['labels'][base_first[s]['chosen']] for s in ordered],
        [cost_first[s]['labels'][cost_first[s]['chosen']] for s in ordered])
    assert all(E.sha(head['neural_source']) == head['neural_sha256'] for head in heads)
    E.write(out/'choices.json', records)
    result = dict(status='complete', experiment='E188', arms=summaries, cost_vs_base=matched,
        closed_form_fits=6, fitted_coefficients_per_head=64, neural_optimizer_updates=0, new_games=0,
        objective_checks=checks, policy_adoption=False, unused_acceptance_games=0,
        cost_candidate_eligible_for_separate_design=bool(summaries['cost']['action_gate_passed'] and matched['net_gain'] >= 0),
        source_neural_weights_unchanged=True, all_head_fit_families_disjoint_from_neural_gradient_and_outer=True,
        limits=plan['limits'])
    E.write(out/'report.json', result)
    E.write(out/'completion.json', dict(status='complete', hashes={p.name: E.sha(p) for p in out.iterdir() if p.is_file()}))
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
