"""Read frozen inner models: fit versus validation and bounded survival scores.

No refit, checkpoint reselection, new labels, natural game or model adoption.
"""
import argparse
from pathlib import Path
import sys

import numpy as np
import torch


def main(root, output):
    sys.path.insert(0, str(root / 'program'))
    import heart_combat_pretraining as P
    E, O = P.E, P.O
    plan = P.registered(root)
    assert E.read(root / 'training-review.json')['status'] == 'complete_reviewed'
    torch.set_num_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = P.Data(store, root / 'data')
    width = store.spec['width'] + store.spec['descriptor_dim']
    rows = []
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'
        roles = E.read(directory / 'auxiliary-roles.json')
        inner = data.families_for(roles['inner_train'])
        rng = np.random.default_rng(20260922641 + fold)
        fit_ids = data.sample(inner, rng.random((8192, 2)))
        baseline = data.baseline(inner)
        for role, ids, permitted in [('fit', fit_ids, set(roles['inner_train'])),
                                     ('validation', np.array(roles['validation_ids']), set(roles['inner_validation']))]:
            for step in P.RECIPE['checkpoints']:
                model = P.auxiliary_model(width, fold)
                model.load_state_dict(torch.load(directory / f'aux-inner-{step}.pt', weights_only=True, map_location='cpu'))
                predictions = []
                with torch.inference_mode():
                    for start in range(0, len(ids), 128):
                        features, labels = data.batch(ids[start:start+128], permitted)
                        predictions.append(model(features).numpy())
                pred = np.concatenate(predictions)
                target = data.targets[ids]
                bounded = pred.copy(); bounded[:, 1] = bounded[:, 1].clip(0, 1)
                old = baseline[data.cells[ids]]
                rows.append(dict(fold=fold, role=role, step=step,
                    mse=((pred - target) ** 2).mean(axis=0).tolist(),
                    clipped_mse=((bounded - target) ** 2).mean(axis=0).tolist(),
                    baseline_mse=((old - target) ** 2).mean(axis=0).tolist(),
                    survival_mean=float(pred[:, 1].mean()), survival_target_mean=float(target[:, 1].mean()),
                    survival_outside_unit=int(((pred[:, 1] < 0) | (pred[:, 1] > 1)).sum()),
                    death_mse=((pred[target[:, 1] == 0] - target[target[:, 1] == 0]) ** 2).mean(axis=0).tolist(),
                    living_mse=((pred[target[:, 1] == 1] - target[target[:, 1] == 1]) ** 2).mean(axis=0).tolist()))
        print(dict(fold=fold, rows=len(rows)), flush=True)
    x = O.C.D.runtime(plan['runtime'])
    candidate_rows_with_cards = 0
    for at in range(0, len(data.edges), 1024):
        actions = store.edge_action[data.edges[at:at+1024]]
        desc = store.descriptors.take(actions)
        cols = desc.indices()[1]
        selected = (cols >= x.A.OFF_CARD) & (cols < x.A.OFF_CARD + x.A.CARD_CAP)
        candidate_rows_with_cards += len(torch.unique(desc.indices()[0, selected]))
    result = dict(status='complete', experiment='E164', rows=rows,
        auxiliary_card_candidate_rows=candidate_rows_with_cards, auxiliary_rows=len(data.edges),
        representation_limit='Current deck counts and offered card identity use separate first-layer columns. Map-only auxiliary examples train deck-state columns but do not present selected card identities; this is a structural coverage fact, not an empirical proof of the policy failure cause.',
        clipping_scope='Projection of a survival prediction into [0,1] cannot increase squared error against binary survival. Diagnostic only; the registered gate and selected checkpoints are unchanged.',
        learning_completion_sha256=E.sha(root / 'learning/completion.json'), reviewer_sha256=E.sha(__file__),
        optimizer_updates=0, new_games=0)
    E.write(output, result)
    for role in ('fit', 'validation'):
        final = [r for r in rows if r['role'] == role and r['step'] == 5000]
        print(dict(role=role, step=5000, mse=np.mean([r['mse'] for r in final], axis=0).tolist(),
            clipped_mse=np.mean([r['clipped_mse'] for r in final], axis=0).tolist(),
            baseline_mse=np.mean([r['baseline_mse'] for r in final], axis=0).tolist()))
    print(dict(auxiliary_card_candidate_rows=candidate_rows_with_cards))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.study.resolve(), args.output.resolve())
