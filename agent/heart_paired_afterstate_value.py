"""Learn card-value differences between actual public acquisition states.

Both targets use the same frozen parent continuation. The resulting scorer is
diagnostic until a separately checked public-effect adapter and natural pilot
exist; recorded successors must never be looked up during deployment.
"""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as NN

import heart_parent_state_value as V

E, O = V.E, V.O
RECIPE = dict(steps=5000, batch_size=128, learning_rate=.0003, weight_decay=.0001,
    gradient_norm=1., calibration_weight=1., seed=2026092375,
    checkpoints=[0, 100, 250, 500, 1000, 2000, 5000], parent_margin=1e-6,
    bootstrap_draws=10000, bootstrap_seed=2026092475)
PAIR_ONLY_RECIPE = dict(RECIPE, calibration_weight=0.)


def recipe_for(experiment):
    E.require(experiment in ('E175', 'E176'), 'unregistered afterstate objective')
    return RECIPE if experiment == 'E175' else PAIR_ONLY_RECIPE


def registered(root):
    reg = E.read(root / 'registration.json')
    E.require(reg['runner_sha256'] == E.sha(__file__), 'paired-afterstate runner changed')
    for path, digest in reg['hashes'].items():
        E.require(E.sha(path) == digest, 'bound source changed: '+path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['recipe'] == recipe_for(plan['experiment'])
              and plan['new_training_rollouts'] == 0, 'paired-afterstate plan changed')
    if plan['experiment'] == 'E176':
        previous = Path(plan['preceding_study'])
        result = E.read(previous / 'training-review.json')
        gradient = E.read(previous / 'gradient-diagnosis.json')
        E.require(result['status'] == 'complete_reviewed' and not result['learning_gate_passed'],
                  'missing reviewed calibrated comparison')
        E.require(gradient['status'] == 'complete_reviewed'
                  and gradient['training_review_sha256'] == E.sha(previous / 'training-review.json'),
                  'missing objective gradient diagnosis')
        old = E.read(previous / 'protocol.json')
        for key in ('learning_source', 'diagnosis', 'runtime', 'natural_source', 'value_source',
                    'ranking_source', 'input_columns', 'scope', 'targets', 'inputs', 'sampling',
                    'stopping', 'learning_gate'):
            E.require(plan[key] == old[key], 'pair-only control changed '+key)
    source = Path(plan['value_source'])
    control = E.read(source / 'protocol.json')
    review = E.read(source / 'training-review.json')
    E.require(review['status'] == 'complete_reviewed' and not review['prediction_gate_passed'],
              'the warm predictor must retain its failed prediction gate')
    E.require(review['learning_completion_sha256'] == E.sha(source / 'learning/completion.json'),
              'warm learning proof differs')
    E.require(plan['input_columns'] == control['input_columns']
              and plan['learning_source'] == control['learning_source'], 'public input changed')
    rank = Path(plan['ranking_source'])
    ranked = E.read(rank / 'result.json')
    E.require(ranked['status'] == 'complete_reviewed'
              and ranked['choices_sha256'] == E.sha(rank / 'choices.json'), 'card scope not reviewed')
    return plan


def prepare(root):
    plan = registered(root)
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    # NPZ access decompresses the whole array; materialize each once.
    targets, best = exact['parent_value'], exact['observed_best']
    value = V.Data(store, Path(plan['value_source']) / 'data', plan['input_columns'])
    E.require(np.array_equal(targets, value.targets), 'fixed-parent targets changed')
    source_rows = E.read(Path(plan['ranking_source']) / 'choices.json')
    families = {f['seed']: f for f in store.families}
    rows, pairs, audit = [], [], Counter()
    matrices = {'all': Counter(), 'initial': Counter(), 'later': Counter()}
    for old in source_rows:
        family = families[old['seed']]
        state, edges = old['state'], np.array(old['edges'], dtype=np.int64)
        E.require(family['begin'] <= state < family['end'] and np.all(store.edge_state[edges] == state)
                  and not bool(store.done[edges].any()), 'invalid card source edge')
        successors = store.next_state[edges]
        E.require(bool(((successors >= family['begin']) & (successors < family['end'])).all()),
                  'card successor crossed family')
        parent = old['parent']
        E.require(store.edge_action[edges[parent]] == store.parent[state], 'card parent changed')
        E.require(targets[state] == targets[successors[parent]]
                  and np.array_equal(targets[successors], old['labels']), 'card continuation label differs')
        row = {key: old[key] for key in ('seed', 'state', 'edges', 'actions', 'parent', 'act', 'floor')}
        row.update(successors=successors.tolist(), pair_begin=len(pairs))
        for j, successor in enumerate(successors):
            if j == parent:
                continue
            pairs.append([len(rows), j])
            before = int(best[successor]-best[successors[parent]])
            after = int(targets[successor]-targets[successors[parent]])
            matrices['all'][f'{before}->{after}'] += 1
            matrices['initial' if row['act'] == 1 else 'later'][f'{before}->{after}'] += 1
        row['pair_end'] = len(pairs)
        audit['changed_states'] += int(not np.array_equal(targets[successors], best[successors]))
        audit['parent_optimism'] += int(best[successors[parent]] > targets[successors[parent]])
        audit['alternative_optimism'] += sum(int(best[s] > targets[s]) for j, s in enumerate(successors) if j != parent)
        rows.append(row)
    E.require(len(rows) == 6264 and len(pairs) == 18759, 'card scope changed')
    E.require(Counter(r['seed'] for r in rows if r['act'] == 1 and r['floor'] == 1)
              == Counter(families.keys()), 'initial natural families missing')
    out = root / 'data'; out.mkdir()
    E.write(out / 'rows.json', rows)
    np.save(out / 'pairs.npy', np.array(pairs, dtype=np.int64), allow_pickle=False)
    report = dict(status='complete', states=len(rows), pairs=len(pairs), families=len(families),
        label_audit=dict(audit), old_to_fixed_parent_differences={k: dict(v) for k, v in matrices.items()},
        fixed_continuation_pair_counts={str(d): sum(v for k, v in matrices['all'].items() if k.endswith('->'+str(d))) for d in (-1, 0, 1)},
        new_games=0, optimizer_updates=0)
    E.write(out / 'report.json', report)
    E.write(out / 'completion.json', dict(status='complete', hashes={p.name: E.sha(p) for p in out.iterdir()}))
    print(report, flush=True)


class Data:
    def __init__(self, store, root, value_root, columns):
        E.proof(root, 'completion.json')
        self.store = store
        self.value = V.Data(store, value_root, columns)
        self.rows = E.read(root / 'rows.json')
        self.pairs = np.load(root / 'pairs.npy', allow_pickle=False)
        self.by_seed = {f['seed']: [] for f in store.families}
        for i, row in enumerate(self.rows):
            self.by_seed[row['seed']].append(i)
        E.require(all(self.by_seed.values()), 'family without card scope')

    def sample(self, families, uniforms):
        pair_ids, calibration = [], []
        for a, b, c, d in uniforms:
            family = families[min(int(a*len(families)), len(families)-1)]
            menus = self.by_seed[family['seed']]
            row = self.rows[menus[min(int(b*len(menus)), len(menus)-1)]]
            pair_ids.append(row['pair_begin']+min(int(c*(row['pair_end']-row['pair_begin'])), row['pair_end']-row['pair_begin']-1))
            calibration.append(family['begin']+min(int(d*(family['end']-family['begin'])), family['end']-family['begin']-1))
        return np.array(pair_ids, dtype=np.int64), np.array(calibration, dtype=np.int64)

    def batch(self, pair_ids, calibration, allowed):
        E.require(len(pair_ids) == len(calibration) and len(pair_ids) > 0
                  and bool(((pair_ids >= 0) & (pair_ids < len(self.pairs))).all()), 'invalid pair batch')
        alternatives, parents = [], []
        for pair_id in pair_ids:
            row_id, candidate = self.pairs[pair_id]
            row = self.rows[row_id]
            E.require(row['seed'] in allowed, 'held family requested as pair fitting label')
            alternatives.append(row['successors'][candidate])
            parents.append(row['successors'][row['parent']])
        # V.Data checks actual ownership of every successor and calibration
        # state before any label read, independently of the row's claimed seed.
        ids = np.array(alternatives+parents+calibration.tolist(), dtype=np.int64)
        return self.value.batch(ids, allowed)

    def subset(self, families):
        return [i for family in families for i in self.by_seed[family['seed']]]


def warm_model(source, width, fold, inner):
    directory = source / 'learning' / f'fold-{fold}'
    control = E.read(source / 'protocol.json')
    selected = E.read(directory / 'report.json')['selected_steps']
    path = directory / (f'inner-{selected}.pt' if inner else 'value.pt')
    saved = torch.load(path, weights_only=True, map_location='cpu')
    weights = saved if inner else saved['model_state']
    model = V.warm_model(Path(control['encoder_source']), width, fold, inner)
    model.load_state_dict(weights)
    return model


def paired_loss(logits, labels, calibration_weight):
    E.require(logits.ndim == labels.ndim == 1 and logits.shape == labels.shape
              and len(logits) > 0 and len(logits) % 3 == 0, 'invalid paired loss shape')
    n = len(logits)//3
    probability = logits[:2*n].sigmoid()
    difference = probability[:n]-probability[n:]
    target = labels[:n]-labels[n:2*n]
    comparison = (difference-target).square().mean()
    calibration = NN.binary_cross_entropy_with_logits(logits[2*n:], labels[2*n:])
    return comparison+calibration_weight*calibration


def select(scores, parent, enabled=True):
    E.require(len(scores) >= 2 and 0 <= parent < len(scores) and np.isfinite(scores).all(), 'invalid public menu scores')
    if not enabled:
        return parent
    best = max(range(len(scores)), key=lambda j: (scores[j], j == parent, -j))
    return parent if scores[best]-scores[parent] <= RECIPE['parent_margin'] else best


def score(model, data, row_ids, allowed, enabled=True):
    rows = [data.rows[i] for i in row_ids]
    E.require(all(row['seed'] in allowed for row in rows), 'held card labels requested for fit role')
    ids = np.unique([s for row in rows for s in row['successors']])
    predictions = {}
    with torch.inference_mode():
        for at in range(0, len(ids), 128):
            features, _ = data.value.batch(ids[at:at+128], allowed)
            values = model(features).squeeze(-1).sigmoid().numpy()
            predictions.update(zip(map(int, ids[at:at+128]), map(float, values)))
    choices = []
    for i, row in zip(row_ids, rows):
        scores = [predictions[s] for s in row['successors']]
        chosen = select(scores, row['parent'], enabled)
        labels = data.value.targets[row['successors']].astype(np.int64).tolist()
        choices.append(dict(row=i, seed=row['seed'], parent=row['parent'], chosen=chosen,
            initial=row['act'] == 1 and row['floor'] == 1, scores=scores, labels=labels))
    return choices


def summarize(choices):
    counts = Counter(states=len(choices)); family = {}
    for row in choices:
        old, new = row['labels'][row['parent']], row['labels'][row['chosen']]
        counts.update(parent_wins=old, chosen_wins=new, available_wins=max(row['labels']),
            changed=int(row['parent'] != row['chosen']), gained=int(new > old), lost=int(new < old))
        family.setdefault(row['seed'], []).append(new-old)
    deltas = {str(seed): float(np.mean(values)) for seed, values in sorted(family.items())}
    return dict(counts, families=len(deltas), family_mean_gain=float(np.mean(list(deltas.values()))), family_deltas=deltas)


def selection_key(row):
    return (round(row['family_mean_gain'], 12), -row['changed'], -row['step'])


def fit(model, data, families, steps, fold, checkpoint=None, recipe=None):
    recipe = RECIPE if recipe is None else recipe
    optimizer = torch.optim.AdamW(model.parameters(), lr=recipe['learning_rate'], weight_decay=recipe['weight_decay'])
    rng = np.random.default_rng(recipe['seed']+fold)
    allowed = {f['seed'] for f in families}
    if checkpoint: checkpoint(0, model)
    for step in range(1, steps+1):
        pairs, calibration = data.sample(families, rng.random((recipe['batch_size'], 4)))
        features, labels = data.batch(pairs, calibration, allowed)
        loss = paired_loss(model(features).squeeze(-1), labels, recipe['calibration_weight'])
        O.gradient_step(loss, optimizer, model, recipe['gradient_norm'])
        if checkpoint and step in recipe['checkpoints']: checkpoint(step, model)


def screen(choices):
    overall = summarize(choices)
    initial = summarize([row for row in choices if row['initial']])
    values = np.array(list(overall['family_deltas'].values()))
    rng = np.random.default_rng(RECIPE['bootstrap_seed'])
    draws = []
    for at in range(0, RECIPE['bootstrap_draws'], 100):
        count = min(100, RECIPE['bootstrap_draws']-at)
        draws.extend(values[rng.integers(len(values), size=(count, len(values)))].mean(axis=1).tolist())
    lower, upper = map(float, np.quantile(draws, [.025, .975]))
    folds = {str(f): summarize([row for row in choices if O.T.fold(row['seed']) == f]) for f in range(3)}
    passed = lower > 0 and initial['chosen_wins'] > initial['parent_wins'] and all(round(r['family_mean_gain'], 12) > 0 for r in folds.values())
    return dict(all_states=overall, initial=initial, folds=folds, family_bootstrap_95=[lower, upper],
                learning_gate_passed=passed)


def train(root):
    plan = registered(root)
    recipe = plan['recipe']
    reviewed = E.read(root / 'data-review.json')
    E.require(reviewed['status'] == 'complete_reviewed'
              and reviewed['data_completion_sha256'] == E.sha(root / 'data/completion.json'), 'pair data not reviewed')
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    source = Path(plan['value_source'])
    data = Data(store, root / 'data', source / 'data', plan['input_columns'])
    width = store.spec['width']+store.spec['descriptor_dim']
    out = root / 'learning'; out.mkdir()
    reports, held_choices = [], []
    for fold in range(3):
        families = [f for f in store.families if O.T.fold(f['seed']) != fold]
        held = [f for f in store.families if O.T.fold(f['seed']) == fold]
        inner, valid = O.inner_partition(families)
        roles = E.read(source / 'learning' / f'fold-{fold}/roles.json')
        for key, group in (('inner_train', inner), ('inner_validation', valid), ('fit', families), ('held', held)):
            E.require(roles[key] == [f['seed'] for f in group], 'warm model family roles differ')
        directory = out / f'fold-{fold}'; directory.mkdir()
        E.write(directory / 'roles.json', {key: roles[key] for key in ('inner_train', 'inner_validation', 'fit', 'held')})
        model = warm_model(source, width, fold, True)
        curve = []
        def checkpoint(step, current):
            choices = score(current, data, data.subset(valid), set(roles['inner_validation']))
            summary = summarize(choices)
            curve.append(dict(step=step, **summary))
            torch.save(current.state_dict(), directory / f'inner-{step}.pt')
        fit(model, data, inner, recipe['steps'], fold, checkpoint, recipe)
        chosen = max(curve, key=selection_key)
        enabled = round(chosen['family_mean_gain'], 12) > 0
        selected = chosen['step'] if enabled else 0
        model = warm_model(source, width, fold, False)
        fit(model, data, families, selected, fold, recipe=recipe)
        torch.save(dict(model_type='paired_afterstate_heart_value', prediction_only=True,
            decision_enabled=enabled, model_state=model.state_dict(), feature_spec=store.spec,
            input_columns=plan['input_columns'], paired_width=width,
            provenance=dict(fold=fold, fit_families=roles['fit'], selected_steps=selected,
                value_sha256=E.sha(source / 'learning' / f'fold-{fold}/value.pt'), recipe=recipe)), directory / 'value.pt')
        fit_choices = score(model, data, data.subset(families), set(roles['fit']), enabled)
        held = score(model, data, data.subset(held), set(roles['held']), enabled)
        held_choices.extend(held)
        E.write(directory / 'stopping.json', curve)
        E.write(directory / 'fit-choices.json', fit_choices)
        E.write(directory / 'held-choices.json', held)
        report = dict(fold=fold, selected_steps=selected, decision_enabled=enabled,
            fit=summarize(fit_choices), held=summarize(held))
        E.write(directory / 'report.json', report)
        reports.append(report)
        print(dict(fold=fold, selected_steps=selected, decision_enabled=enabled,
            fit_gain=report['fit']['family_mean_gain'], held_gain=report['held']['family_mean_gain']), flush=True)
    report = dict(status='complete', experiment=plan['experiment'], **screen(held_choices),
        folds_training=[dict(fold=r['fold'], selected_steps=r['selected_steps'], decision_enabled=r['decision_enabled']) for r in reports],
        value_optimizer_updates=3*recipe['steps']+sum(r['selected_steps'] for r in reports),
        new_games=0, auxiliary_optimizer_updates=0, policy_adoption=False,
        limits='Correlated old card afterstates with a fixed continuation, not a natural or unseen win rate. Gate passage permits separate public-effect and natural-pilot verification only.')
    E.write(out / 'report.json', report)
    E.write(out / 'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'prepare': prepare, 'train': train, 'check': registered}[args.command](args.study.resolve())
