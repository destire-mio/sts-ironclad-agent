"""Read-only accounting of E158 supervision and frozen branch choices.

Reconstruct deterministic fitting draws; do not fit or run games. The diagnostic
uses all existing branch states and reports fit appearances separately from held
families. Observed-graph outcomes are hindsight references, not new win rates.
"""
import argparse
from collections import Counter, defaultdict
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(source, output):
    sys.path.insert(0, str(source / 'program'))
    import heart_exact_control as F
    E, O = F.E, F.O
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    plan = F.registered(source)
    assert E.read(source / 'result-review.json')['status'] == 'complete_reviewed'
    E.proof(source / 'learning', 'completion.json')
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    q = np.where(store.done, store.reward, exact['observed_best'][store.next_state])
    states = np.flatnonzero(np.diff(store.state_edge_ptr) > 1)
    improved = np.zeros(store.states, dtype=bool)
    owners = np.empty(store.states, dtype=np.int64)
    for i, family in enumerate(store.families):
        owners[family['begin']:family['end']] = i
    for state in states:
        a, b = store.state_edge_ptr[state:state + 2]
        edges = store.state_edge_ids[a:b]
        parent = edges[store.edge_action[edges] == store.parent[state]]
        assert len(parent) == 1
        improved[state] = q[parent[0]] < q[edges].max()
    assert int(improved.sum()) == 449
    spec = importlib.util.spec_from_file_location('numpy_review', Path(__file__).with_name('e154-review.py'))
    independent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(independent)
    groups = defaultdict(Counter)
    draws = []
    error = 0.
    for fold in range(3):
        directory = source / 'learning' / f'fold-{fold}'
        cp = torch.load(directory / 'candidate.pt', map_location='cpu', weights_only=True)
        families = [f for f in store.families if O.T.fold(f['seed']) != fold]
        inner, validation = O.inner_partition(families)
        selected = cp['provenance']['selected_actor_steps']
        for label, members, steps, salt in (
            ('inner_fit', inner, O.RECIPE['actor_steps'], 1000),
            ('refit', families, selected, 1000),
            ('inner_validation', validation, None, 2000),
        ):
            size = steps * O.RECIPE['batch_size'] if steps is not None else O.RECIPE['validation_draws']
            rng = np.random.default_rng(O.RECIPE['seed'] + salt + fold)
            edges = O.sample_edges(store, members, rng.random((size, 4)))
            sampled_states = store.edge_state[edges]
            if label == 'inner_validation':
                assert edges.tolist() == E.read(directory / 'actor-validation.json')['edges']
            probability = sum(sum(float(improved[np.asarray(group)].mean()) for group in f['strata']) / len(f['strata']) for f in members) / len(members)
            draws.append(dict(fold=fold, role=label, draws=size,
                alternative_teacher_draws=int(improved[sampled_states].sum()),
                distinct_alternative_teacher_states=int(np.unique(sampled_states[improved[sampled_states]]).size),
                expected_alternative_probability=probability))
        actor = O.Actor(store.spec['width'])
        actor.load_state_dict(cp['actor_state'])
        actor.eval()
        supported = O.supported_candidates(store, set(cp['support']))
        for at in range(0, len(states), 64):
            batch = states[at:at + 64]
            representative = store.state_edge_ids[store.state_edge_ptr[batch]]
            features, ptr, _, parents, actions = store.menu(representative)
            dense = features.to_dense()
            with torch.inference_mode():
                scores = actor(dense).numpy()
            reference = independent.forward(cp['actor_state'], dense.numpy())
            error = max(error, float(np.max(np.abs(scores - reference))))
            assert np.allclose(scores, reference, rtol=1e-4, atol=1e-4)
            scores[parents] += O.RECIPE['parent_bonus']
            allowed = supported[actions].copy()
            allowed[parents] = True
            scores[~allowed] = -np.inf
            for i, state in enumerate(batch):
                a, b = ptr[i:i + 2]
                parent = int(parents[i] - a)
                choice = max(np.flatnonzero(allowed[a:b]), key=lambda k: (float(scores[a+k]), k == parent, -k))
                u, v = store.state_edge_ptr[state:state + 2]
                edges = store.state_edge_ids[u:v]
                found = edges[store.edge_action[edges] == store.menu_ptr[state] + choice]
                family = store.families[owners[state]]
                role = 'held' if O.T.fold(family['seed']) == fold else 'fit'
                group = 'improvement_available' if improved[state] else 'parent_is_best'
                row = groups[role, group]
                row['appearances'] += 1
                row['parent_choices'] += int(choice == parent)
                row['unrecorded_choices'] += int(len(found) == 0)
                if len(found):
                    row['recorded_best_choices'] += int(q[found[0]] == q[edges].max())
                if improved[state]:
                    best_positions = store.edge_action[edges[q[edges] == q[edges].max()]] - store.menu_ptr[state]
                    margin = float(scores[a + best_positions].max() - scores[a + parent])
                    row['best_alternative_minus_parent_score_sum'] += margin
                    row['best_alternative_exceeds_parent_score'] += int(margin > 0.)
        print(dict(fold=fold, stage='verified_branch_choices'), flush=True)
    result = dict(status='complete', experiment='E159-supervision', source=str(source),
        source_learning_sha256=E.sha(source / 'learning' / 'completion.json'),
        source_runner_sha256=E.sha(source / 'program' / 'heart_exact_control.py'),
        sampler_sha256=E.sha(source / 'program' / 'heart_offline_control.py'),
        script_sha256=E.sha(__file__), independent_forward_sha256=E.sha(independent.__file__),
        reconstructed_draws=draws,
        branch_choices={role: {tag: dict(counts) for (r, tag), counts in groups.items() if r == role} for role in ('fit', 'held')},
        numpy_maximum_score_error=error, verified_branch_choices=3 * len(states),
        optimizer_updates=0, new_games=0,
        limits='Draw counts are reconstructed from frozen RNG and sampler, not new training. Fit branch appearances count each family twice; held once. Recorded maximum outcomes use hidden future knowledge and are not policy win rates.')
    E.write(output, result)
    print(result, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    main(a.source.resolve(), a.output.resolve())
