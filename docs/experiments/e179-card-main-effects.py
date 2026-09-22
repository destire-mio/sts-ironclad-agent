"""Fixed ridge control for stable card effects on old combat pair labels."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(root):
    plan = json.loads((root / 'protocol.json').read_text())
    registration = json.loads((root / 'registration.json').read_text())
    for path, digest in registration['hashes'].items(): assert sha(path) == digest, path
    source = Path(plan['source']); sys.path.insert(0, str(source / 'program'))
    import heart_card_combat_delta as D
    E, O = D.E, D.O
    old = D.registered(source)
    review = E.read(source / 'training-review.json')
    assert review['status'] == 'complete_reviewed' and not review['auxiliary_gate_passed']
    assert review['learning_completion_sha256'] == E.sha(source / 'learning/completion.json')
    store = O.Store(Path(old['learning_source']) / 'store'); data = D.Data(store, old)
    x = O.C.D.runtime(old['runtime'])
    offset = O.C.D.feature_spec(x)['deck_offset']; count = 2*x.A.CARD_CAP
    columns = [store.spec['observations'].index(raw) for raw in range(offset, offset+count)]
    columns.append(store.spec['observations'].index(1))
    assert set(columns).issubset(old['input_columns'])
    scales = np.r_[np.full(count, 20.), 100.]  # one card, or two maximum HP
    lookup = {column: i for i, column in enumerate(columns)}
    def feature(state):
        result = np.zeros(len(columns))
        a, b = store.shared.ptr[state:state+2]
        for column, value in zip(store.shared.cols[a:b], store.shared.values[a:b]):
            if column in lookup: result[lookup[column]] = value
        return result*scales
    features = np.zeros((len(data.pairs), len(columns))); targets = np.zeros((len(data.pairs), 2))
    owners = np.zeros(len(data.pairs), dtype=np.int64); weight = np.zeros(len(data.pairs))
    for seed, menus in data.by_seed.items():
        for row_id in menus:
            row = data.rows[row_id]; parent = row['successors'][row['parent']]
            original = feature(parent)
            for pair_id in data.menu_pairs[row_id]:
                candidate = data.pairs[pair_id, 1]; state = row['successors'][candidate]
                features[pair_id] = feature(state)-original
                targets[pair_id] = data.targets[data.first[state]]-data.targets[data.first[parent]]
                owners[pair_id] = seed
                weight[pair_id] = 1./(len(menus)*len(data.menu_pairs[row_id]))
    assert np.count_nonzero(weight) == 18682
    for seed in data.by_seed: assert abs(weight[owners == seed].sum()-1) < 1e-12
    # Native public counts recover integer acquired/removed card quantities;
    # no future outcome or encounter contributes to these features.
    np.testing.assert_allclose(features[:, :count], np.rint(features[:, :count]), atol=1e-5, rtol=0)
    out = root / 'learning'; out.mkdir(); reports = []
    for fold in range(3):
        directory = out / f'fold-{fold}'; directory.mkdir()
        roles = E.read(source / 'learning' / f'fold-{fold}/roles.json')
        report = dict(fold=fold)
        for inner in (True, False):
            role = 'inner_train' if inner else 'fit'
            ids = np.flatnonzero((weight > 0) & np.isin(owners, roles[role]))
            assert not set(owners[ids]) & set(roles['held'])
            active = np.flatnonzero(np.any(features[ids] != 0, axis=0))
            matrix = features[np.ix_(ids, active)]; weighted = matrix*weight[ids, None]
            normal = matrix.T @ weighted + plan['ridge_strength']*np.eye(len(active))
            rhs = weighted.T @ targets[ids]
            coefficients = np.zeros((len(columns), 2))
            coefficients[active] = np.linalg.solve(normal, rhs)
            residual = float(np.max(np.abs(normal@coefficients[active]-rhs)))
            assert residual < 1e-8 and np.isfinite(coefficients).all()
            fit_error = np.sum(weight[ids, None]*(features[ids]@coefficients-targets[ids])**2, axis=0)/weight[ids].sum()
            evaluate = np.array(roles['validation_pairs' if inner else 'held_pairs'])
            assert bool((weight[evaluate] > 0).all())
            expected_role = roles['inner_validation' if inner else 'held']
            assert set(owners[evaluate]).issubset(expected_role)
            mse = np.mean((features[evaluate]@coefficients-targets[evaluate])**2, axis=0)
            baseline = np.mean(targets[evaluate]**2, axis=0)
            if not inner:
                np.testing.assert_allclose(baseline, E.read(source / 'learning' / f'fold-{fold}/report.json')['zero_baseline_mse'], atol=1e-8, rtol=0)
            name = 'inner' if inner else 'final'
            np.save(directory / f'{name}-coefficients.npy', coefficients, allow_pickle=False)
            report[name] = dict(fit_pairs=len(ids), fit_families=len(roles[role]), active_features=len(active),
                fitted_coefficients=2*len(active), normal_equation_maximum_residual=residual,
                fit_mse=fit_error.tolist(), evaluation_pairs=len(evaluate), evaluation_mse=mse.tolist(), zero_baseline_mse=baseline.tolist())
        E.write(directory / 'report.json', report); reports.append(report)
    error = float(np.mean([r['final']['evaluation_mse'] for r in reports]))
    baseline = float(np.mean([r['final']['zero_baseline_mse'] for r in reports]))
    passed = error <= .9*baseline and all(np.mean(r['final']['evaluation_mse']) < np.mean(r['final']['zero_baseline_mse']) for r in reports)
    report = dict(status='complete_reviewed', experiment='E179', folds=reports, held_mse=error,
        zero_baseline_mse=baseline, relative_improvement=1-error/baseline, auxiliary_gate_passed=bool(passed),
        closed_form_fits=6, gradient_optimizer_updates=0, new_games=0, policy_adoption=False,
        public_feature_columns=columns, all_features_native_card_count_units_verified=True,
        all_fit_family_weights_sum_to_one=True, original_E178_held_draws_and_baselines_verified=True,
        source_review_sha256=E.sha(source / 'training-review.json'), runner_sha256=E.sha(__file__),
        limits=plan['limits'])
    E.write(out / 'report.json', report)
    E.write(out / 'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print({k: v for k, v in report.items() if k != 'public_feature_columns'}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
