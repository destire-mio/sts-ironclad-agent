"""Inspect every retained E165 inner model without fitting or selecting a policy."""
import argparse
from collections import Counter, defaultdict
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(source, output):
    sys.path.insert(0, str(source / 'program'))
    import heart_expected_improvement as I
    E, O = I.E, I.O
    import heart_combat_local_inputs as L
    plan = L.registered(source)
    assert E.read(source / 'training-review.json')['status'] == 'complete_reviewed'
    E.proof(source / 'learning', 'completion.json')
    spec = importlib.util.spec_from_file_location('review', Path(__file__).with_name('e165-heart-review.py'))
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    examples = I.Examples(store, exact['observed_best'])
    owner = np.empty(store.states, dtype=np.int64)
    for family in store.families:
        owner[family['begin']:family['end']] = family['seed']
    states = np.flatnonzero(np.diff(store.state_edge_ptr) > 1)
    report = []
    for fold in range(3):
        directory = source / 'learning' / f'fold-{fold}'
        validation = E.read(directory / 'actor-validation.json')
        fitting = set(validation['inner_train'])
        held = set(validation['inner_validation'])
        included = states[np.isin(owner[states], list(fitting | held))]
        fit_indices = np.concatenate([f['indices'] for f in examples.families if f['seed'] in fitting])
        support = set(store.candidate_identity[store.edge_action[examples.edges[fit_indices]]].tolist())
        curves = E.read(directory / 'stopping.json')
        models = {r['step']: torch.load(directory / f'inner-{r["step"]}.pt', map_location='cpu', weights_only=True) for r in curves}
        counts = {step: {role: Counter() for role in ('inner_fit', 'inner_validation')} for step in models}
        family_deltas = {step: defaultdict(lambda: [0., 0]) for step in models}
        for at in range(0, len(included), 64):
            batch = included[at:at+64]
            sizes = store.menu_ptr[batch+1] - store.menu_ptr[batch]
            ptr = np.r_[0, np.cumsum(sizes)]
            actions = np.concatenate([np.arange(store.menu_ptr[s], store.menu_ptr[s+1]) for s in batch])
            features = R.matrix(store, np.repeat(batch, sizes), actions)
            for step, weights in models.items():
                logits = R.logits(weights, features)
                probability = np.exp(logits - logits.max(axis=1, keepdims=True))
                probability /= probability.sum(axis=1, keepdims=True)
                scores = probability[:, 2] - probability[:, 0]
                for i, state in enumerate(batch):
                    a, b = ptr[i:i+2]
                    seed = int(owner[state])
                    role = 'inner_fit' if seed in fitting else 'inner_validation'
                    row = counts[step][role]
                    parent = int(store.parent[state] - store.menu_ptr[state])
                    scores[a+parent] = 0.
                    allowed = [k for k in range(b-a) if k == parent or int(store.candidate_identity[actions[a+k]]) in support]
                    choice = max(allowed, key=lambda k: (float(scores[a+k]), k == parent, -k))
                    u, v = store.state_edge_ptr[state:state+2]
                    edges = store.state_edge_ids[u:v]
                    row['states'] += 1
                    row['improvement_available'] += int(examples.q[edges].max() > examples.parent_q[state])
                    row['parent_choices'] += int(choice == parent)
                    found = edges[store.edge_action[edges] == store.menu_ptr[state] + choice]
                    if len(found):
                        delta = examples.q[found[0]] - examples.parent_q[state]
                        row['known_gains'] += int(delta > 0)
                        row['known_losses'] += int(delta < 0)
                        row['known_ties'] += int(delta == 0)
                    else:
                        row['unrecorded'] += 1
                        delta = -examples.parent_q[state]
                    family_deltas[step][seed][0] += float(delta)
                    family_deltas[step][seed][1] += 1
        for curve in curves:
            step = curve['step']
            row = dict(fold=fold, step=step, categorical_validation_loss=curve['loss'])
            for role, members in (('inner_fit', fitting), ('inner_validation', held)):
                row[role] = dict(counts[step][role], family_mean_known_delta_lower_bound=float(np.mean([total / n for seed, (total, n) in family_deltas[step].items() if seed in members])))
            report.append(row)
        print(dict(fold=fold, stage='complete'), flush=True)
    result = dict(status='complete', experiment='E165', source=str(source), curves=report,
        source_learning_sha256=E.sha(source / 'learning/completion.json'), source_review_sha256=E.sha(source / 'training-review.json'),
        runner_sha256=E.sha(__file__), independent_math_sha256=E.sha(R.__file__),
        optimizer_updates=0, new_games=0, selected_or_adopted_models=0,
        limits='Uses only inner fitting/validation families, not the excluded outer fold. Counts refer to branch decisions, not games. Unknown outcomes use0 only for a stated pessimistic lower bound, never a recorded death. This diagnosis does not change E165 stopping or adopt any saved model.')
    E.write(output, result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.source.resolve(), args.output.resolve())
