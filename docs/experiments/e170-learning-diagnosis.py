"""Measure fitted-family prediction while retained validation error worsens."""
import argparse
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_parent_state_value as V
    E, O = V.E, V.O
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    plan = V.registered(root)
    reviewed = E.read(root / 'training-review.json')
    assert reviewed['status'] == 'complete_reviewed'
    assert reviewed['learning_completion_sha256'] == E.sha(root / 'learning/completion.json')
    path = Path(__file__).with_name('e170-review.py')
    spec = importlib.util.spec_from_file_location('independent_value_review', path)
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = V.Data(store, root / 'data', plan['input_columns'])
    results = []
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'
        inner = set(E.read(directory / 'roles.json')['inner_train'])
        families = [f for f in data.families if f['seed'] in inner]
        rng = np.random.default_rng(2026092270+fold)
        ids = data.sample(families, rng.random((8192, 2)))
        weights = {step: torch.load(directory / f'inner-{step}.pt', weights_only=True, map_location='cpu')
                   for step in (2000, 5000, 10000, 20000)}
        totals = {step: 0. for step in weights}
        for at in range(0, len(ids), 128):
            rows = ids[at:at+128]
            features = check.matrix(store, rows, plan['input_columns'])
            for step, state in weights.items():
                predictions = check.predict(state, features)
                totals[step] += float(np.sum((predictions-data.targets[rows])**2))
        curve = {r['step']: r['brier'] for r in E.read(directory / 'stopping.json')}
        rows = [dict(step=step, fit_brier=totals[step]/len(ids), validation_brier=curve[step]) for step in weights]
        baseline = np.load(directory / 'inner-baseline.npy', allow_pickle=False)
        result = dict(fold=fold, fit_baseline_brier=float(np.mean((baseline[data.cells[ids]]-data.targets[ids])**2)), curve=rows)
        results.append(result); print(result, flush=True)
    E.write(root / 'learning-diagnosis.json', dict(status='complete_reviewed', experiment='E170',
        folds=results, optimizer_updates=0, new_games=0, held_result_used_to_select_checkpoint=False,
        training_review_sha256=E.sha(root / 'training-review.json'), runner_sha256=E.sha(__file__),
        inference_reviewer_sha256=E.sha(path),
        limits='Fit/inner-validation diagnosis on retained checkpoints; no checkpoint selected from outer outcomes.'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
