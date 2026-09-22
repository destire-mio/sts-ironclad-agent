"""Independent categorical loss, stopping and full-menu branch screen review."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def matrix(store, states, actions):
    public = store.action_features(states, actions).to_dense().numpy()
    parent = store.descriptors.take(store.parent[states]).to_dense().numpy()
    return np.concatenate([public, parent], axis=1)


def logits(weights, x):
    for layer in ('input', 'tail.1', 'tail.3'):
        x = x @ weights[layer + '.weight'].numpy().T + weights[layer + '.bias'].numpy()
        if layer != 'tail.3':
            x = x / (1 + np.exp(np.clip(-x, -80, 80)))
    return x


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_expected_improvement as I
    E, O = I.E, I.O
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    import heart_combat_local_inputs as L
    P = L.P
    plan = L.registered(root)
    auxiliary = E.read(root / 'auxiliary-review.json')
    assert auxiliary['status'] == 'complete_reviewed' and auxiliary['passed']
    E.proof(root / 'learning', 'completion.json')
    end = E.read(root / 'train-control/exit.json')
    assert end['status'] == 'train_complete' and end['exit_code'] == 0
    process = root / 'train-execution/pipeline-process-exit.json'
    assert E.sha(process) == end['owned_exit_sha256']
    assert E.read(process)['exit_code'] == 0 and E.read(process)['cleanup']['clean']
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    q = np.where(store.done, store.reward, exact['observed_best'][store.next_state])
    parents = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    parent_value = np.zeros(store.states)
    parent_value[store.edge_state[parents]] = q[parents]
    alternatives = np.flatnonzero(store.edge_action != store.parent[store.edge_state])
    labels = (q[alternatives] - parent_value[store.edge_state[alternatives]] + 1).astype(np.int64)
    examples = I.Examples(store, exact['observed_best'])
    assert np.array_equal(alternatives, examples.edges) and np.array_equal(labels, examples.labels)
    base = torch.load(Path(plan['runtime']) / 'model.pt', weights_only=True, map_location='cpu')
    states = np.flatnonzero(np.diff(store.state_edge_ptr) > 1)
    owners = np.empty(store.states, dtype=np.int8)
    for family in store.families:
        owners[family['begin']:family['end']] = O.T.fold(family['seed'])
    aggregate = {role: Counter() for role in ('fit', 'held')}
    maximum_error = 0.
    steps = []
    checkpoints = 0
    for fold in range(3):
        directory = root / 'learning' / f'fold-{fold}'
        record = E.read(directory / 'actor-validation.json')
        fitting = [f for f in examples.families if O.T.fold(f['seed']) != fold]
        inner, valid = O.inner_partition(fitting)
        assert record['inner_train'] == [f['seed'] for f in inner]
        assert record['inner_validation'] == [f['seed'] for f in valid]
        rng = np.random.default_rng(I.RECIPE['seed'] + 2000 + fold)
        ids = examples.sample(valid, rng.random((I.RECIPE['validation_draws'], 3)))
        assert ids.tolist() == record['indices']
        curve = E.read(directory / 'stopping.json')
        assert [r['step'] for r in curve] == list(O.CHECKPOINTS)
        weights = {r['step']: torch.load(directory / f'inner-{r["step"]}.pt', weights_only=True, map_location='cpu') for r in curve}
        aux_selected = auxiliary['selected_steps'][fold]
        warm = P.auxiliary_model(store.spec['width'] + store.spec['descriptor_dim'], fold)
        warm.load_state_dict(torch.load(directory / f'aux-inner-{aux_selected}.pt', weights_only=True, map_location='cpu'))
        expected_initial = P.reset_heart_head(warm).state_dict()
        assert all(torch.equal(v, expected_initial[k]) for k, v in weights[0].items())
        totals = {step: 0. for step in weights}
        for at in range(0, len(ids), 128):
            chosen = ids[at:at+128]
            edges = alternatives[chosen]
            features = matrix(store, store.edge_state[edges], store.edge_action[edges])
            target = labels[chosen]
            for step, weight in weights.items():
                predicted = logits(weight, features).astype(np.float64)
                top = predicted.max(axis=1)
                loss = top + np.log(np.exp(predicted - top[:, None]).sum(axis=1)) - predicted[np.arange(len(target)), target]
                totals[step] += float(loss.sum())
        for r in curve:
            error = abs(totals[r['step']] / len(ids) - r['loss'])
            maximum_error = max(maximum_error, error)
            assert error < 1e-4
            checkpoints += 1
        selected = min(curve, key=lambda r: (r['loss'], r['step']))['step']
        steps.append(selected)
        cp = torch.load(directory / 'candidate.pt', weights_only=True, map_location='cpu')
        assert cp['provenance']['fold'] == fold and cp['provenance']['fit_families'] == [f['seed'] for f in fitting]
        assert cp['provenance']['selected_actor_steps'] == selected and cp['provenance']['recipe'] == I.RECIPE
        assert cp['provenance']['selected_auxiliary_steps'] == auxiliary['selected_steps'][fold]
        assert cp['provenance']['auxiliary_recipe'] == P.RECIPE
        assert cp['feature_spec'] == store.spec and cp['paired_width'] == store.spec['width'] + store.spec['descriptor_dim']
        def same(a, b):
            if isinstance(a, torch.Tensor): return isinstance(b, torch.Tensor) and torch.equal(a, b)
            if isinstance(a, dict): return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
            if isinstance(a, (list, tuple)): return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
            return a == b
        assert same(cp['base_checkpoint'], base)
        all_fit = np.concatenate([f['indices'] for f in fitting])
        support = sorted({store.identities[int(j)] for j in store.candidate_identity[store.edge_action[alternatives[all_fit]]]})
        assert cp['support'] == support
        permitted = {store.identities.index(key) for key in support}
        screen = {role: Counter() for role in ('fit', 'held')}
        for at in range(0, len(states), 64):
            batch = states[at:at+64]
            sizes = store.menu_ptr[batch+1] - store.menu_ptr[batch]
            ptr = np.r_[0, np.cumsum(sizes)]
            actions = np.concatenate([np.arange(store.menu_ptr[s], store.menu_ptr[s+1]) for s in batch])
            prediction = logits(cp['actor_state'], matrix(store, np.repeat(batch, sizes), actions))
            probability = np.exp(prediction - prediction.max(axis=1, keepdims=True))
            probability /= probability.sum(axis=1, keepdims=True)
            scores = probability[:, 2] - probability[:, 0]
            for i, state in enumerate(batch):
                a, b = ptr[i:i+2]
                parent = int(store.parent[state] - store.menu_ptr[state])
                scores[a+parent] = 0.
                allowed = [k for k in range(b-a) if k == parent or int(store.candidate_identity[actions[a+k]]) in permitted]
                choice = max(allowed, key=lambda k: (float(scores[a+k]), k == parent, -k))
                u, v = store.state_edge_ptr[state:state+2]
                edges = store.state_edge_ids[u:v]
                row = screen['held' if owners[state] == fold else 'fit']
                row['states'] += 1
                row['improvement_available'] += int(q[edges].max() > parent_value[state])
                row['parent_choices'] += int(choice == parent)
                selected_edge = edges[store.edge_action[edges] == store.menu_ptr[state] + choice]
                if len(selected_edge) == 0:
                    row['unrecorded_choices'] += 1
                else:
                    delta = q[selected_edge[0]] - parent_value[state]
                    row['known_gains'] += int(delta > 0)
                    row['known_losses'] += int(delta < 0)
                    row['known_ties'] += int(delta == 0)
        assert {k: dict(v) for k, v in screen.items()} == E.read(directory / 'branch-screen.json')
        for role in aggregate:
            aggregate[role].update(screen[role])
        print(dict(fold=fold, stage='independent_review', selected_step=selected), flush=True)
    report = E.read(root / 'learning/report.json')
    assert {k: dict(v) for k, v in aggregate.items()} == report['branch_screen']
    fitted, held = aggregate['fit'], aggregate['held']
    eligible = fitted['known_gains'] >= .5 * fitted['improvement_available'] and fitted['known_gains'] > fitted['known_losses'] and held['known_gains'] > held['known_losses']
    assert eligible == report['eligible_for_natural_evaluation']
    assert report['heart_optimizer_steps'] == 6000 + sum(steps)
    review = dict(status='complete_reviewed', experiment='E165', selected_steps=steps,
        actor_optimizer_steps=report['heart_optimizer_steps'], auxiliary_optimizer_steps=auxiliary['optimizer_steps'],
        auxiliary_review_sha256=E.sha(root / 'auxiliary-review.json'), inner_checkpoints_verified=checkpoints,
        maximum_numpy_loss_error=maximum_error, independent_branch_choices=3 * len(states),
        branch_screen=report['branch_screen'], eligible_for_natural_evaluation=eligible,
        controller_exit_sha256=E.sha(root / 'train-control/exit.json'),
        learning_completion_sha256=E.sha(root / 'learning/completion.json'), reviewer_sha256=E.sha(__file__),
        new_training_rollouts=0, natural_games=0, production_adoption=False,
        limits='Fit branch appearances count each family twice; held once. Recorded-graph outcomes are hindsight and branch scores are not full-game or unseen win rates.')
    E.write(root / 'training-review.json', review)
    print(review)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
