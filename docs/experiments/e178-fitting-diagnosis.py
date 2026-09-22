"""Read-only fit/validation comparison of already saved auxiliary weights."""
import argparse
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_card_combat_delta as D
    E, O = D.E, D.O
    plan = D.registered(root)
    review = E.read(root / 'training-review.json')
    assert review['status'] == 'complete_reviewed' and not review['auxiliary_gate_passed']
    assert review['learning_completion_sha256'] == E.sha(root / 'learning/completion.json')
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    path = Path(__file__).with_name('e178-review.py')
    spec = importlib.util.spec_from_file_location('auxiliary_independent', path)
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    store = O.Store(Path(plan['learning_source']) / 'store'); data = D.Data(store, plan)
    results = []
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'
        roles = E.read(directory / 'roles.json')
        families = [f for f in store.families if f['seed'] in roles['inner_train']]
        draws = data.sample(families, np.random.default_rng(D.RECIPE['seed']+4000+fold).random((8192, 3)))
        curve = {r['step']: r for r in E.read(directory / 'stopping.json')}
        rows = []
        for step in (0, 250, 1000, 5000):
            weights = torch.load(directory / f'inner-{step}.pt', weights_only=True, map_location='cpu')
            error, baseline = check.errors(weights, data, draws, plan['input_columns'])
            rows.append(dict(step=step, fit_mse=error.tolist(), fit_zero_baseline=baseline.tolist(),
                fit_relative_improvement=1-float(np.mean(error)/np.mean(baseline)),
                validation_mse=curve[step]['mse'], validation_zero_baseline=curve[step]['zero_baseline_mse'],
                validation_relative_improvement=1-float(np.mean(curve[step]['mse'])/np.mean(curve[step]['zero_baseline_mse']))))
        results.append(dict(fold=fold, fit_draws=8192, checkpoints=rows))
    result = dict(status='complete_reviewed', experiment='E178_readonly_fitting_diagnosis', folds=results,
        optimizer_updates=0, new_games=0, checkpoint_reselection=False, original_gate_remains_failed=True,
        source_review_sha256=E.sha(root / 'training-review.json'), runner_sha256=E.sha(__file__),
        limits='Post-hoc diagnostic of saved weights on fixed inner fitting draws and original validation. No extra updates, held-result choice, or policy gain claim.')
    E.write(root / 'fitting-diagnosis.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
