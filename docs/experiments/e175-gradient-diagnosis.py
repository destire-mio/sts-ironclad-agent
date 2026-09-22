"""Read-only gradient audit of E175's two objectives at its warm starts."""
import argparse
from pathlib import Path
import sys

import numpy as np
import torch
from torch.nn import functional as F


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_paired_afterstate_value as A
    E, O = A.E, A.O
    plan = A.registered(root)
    review = E.read(root / 'training-review.json')
    assert review['status'] == 'complete_reviewed' and not review['learning_gate_passed']
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = A.Data(store, root / 'data', Path(plan['value_source']) / 'data', plan['input_columns'])
    results = []
    for fold in range(3):
        fit = [f for f in store.families if O.T.fold(f['seed']) != fold]
        inner, _ = O.inner_partition(fit)
        allowed = {f['seed'] for f in inner}
        model = A.warm_model(Path(plan['value_source']), store.spec['width']+store.spec['descriptor_dim'], fold, True)
        initial = {k: v.clone() for k, v in model.state_dict().items()}
        rng = np.random.default_rng(A.RECIPE['seed']+fold)
        ratios, cosines, projections, fractions = [], [], [], []
        for _ in range(64):
            pair_ids, calibration = data.sample(inner, rng.random((A.RECIPE['batch_size'], 4)))
            features, labels = data.batch(pair_ids, calibration, allowed)
            logits = model(features).squeeze(-1); n = len(pair_ids)
            probabilities = logits[:2*n].sigmoid()
            delta = labels[:n]-labels[n:2*n]
            pair_loss = ((probabilities[:n]-probabilities[n:])-delta).square().mean()
            calibration_loss = F.binary_cross_entropy_with_logits(logits[2*n:], labels[2*n:])
            params = tuple(model.parameters())
            paired = torch.autograd.grad(pair_loss, params, retain_graph=True)
            calibrated = torch.autograd.grad(calibration_loss, params)
            pair_norm = sum(float(g.double().square().sum()) for g in paired)
            cal_norm = sum(float(g.double().square().sum()) for g in calibrated)
            dot = sum(float((a.double()*b.double()).sum()) for a, b in zip(paired, calibrated))
            assert pair_norm > 0 and cal_norm > 0
            ratios.append((pair_norm/cal_norm)**.5)
            cosines.append(dot/(pair_norm*cal_norm)**.5)
            projections.append(dot/pair_norm)
            fractions.append(float((delta != 0).float().mean()))
        assert all(torch.equal(v, initial[k]) for k, v in model.state_dict().items())
        results.append(dict(fold=fold, batches=64, pair_examples=64*A.RECIPE['batch_size'],
            informative_fraction=float(np.mean(fractions)),
            pair_to_calibration_gradient_norm_quantiles=np.quantile(ratios, [.1, .5, .9]).tolist(),
            objective_gradient_cosine_quantiles=np.quantile(cosines, [.1, .5, .9]).tolist(),
            calibration_projection_in_pair_gradient_units_quantiles=np.quantile(projections, [.1, .5, .9]).tolist(),
            opposed_objective_batches=int(np.count_nonzero(np.array(cosines) < 0)),
            plain_gradient_sum_would_increase_pair_loss_batches=int(np.count_nonzero(np.array(projections) < -1))))
    report = dict(status='complete_reviewed', experiment='E175_posthoc_gradient_diagnosis', folds=results,
        fixed_warm_weights_verified=True, optimizer_updates=0, new_games=0,
        runner_sha256=E.sha(__file__), training_review_sha256=E.sha(root / 'training-review.json'),
        limits='Same first64 training draws at each untouched inner warm start. Euclidean gradients diagnose local objective scale/conflict, not AdamW update behavior, long-run policy benefit or a causal explanation of the entire failed experiment.')
    E.write(root / 'gradient-diagnosis.json', report)
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
