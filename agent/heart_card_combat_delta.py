"""Auxiliary card-effect learning from already audited mapped-combat outcomes.

Neither output is a Heart objective or a deployed policy score. This experiment
tests transferable supervision; a later Heart experiment must justify any use.
"""
import argparse
from pathlib import Path

import numpy as np
import torch

import heart_paired_afterstate_value as A

E, O, V = A.E, A.O, A.V
RECIPE = dict(steps=5000, batch_size=128, learning_rate=.0003, weight_decay=.0001,
    gradient_norm=1., seed=2026092378, validation_draws=8192,
    checkpoints=[0, 250, 500, 1000, 2000, 5000], relative_mse_gate=.9)


def registered(root):
    reg = E.read(root / 'registration.json')
    E.require(reg['runner_sha256'] == E.sha(__file__), 'card-combat runner changed')
    for path, digest in reg['hashes'].items():
        E.require(E.sha(path) == digest, 'bound source changed: '+path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['experiment'] == 'E178' and plan['recipe'] == RECIPE
              and plan['new_training_rollouts'] == 0, 'auxiliary recipe changed')
    audit = Path(plan['target_source'])
    report = E.read(audit / 'data/report.json')
    E.require(report['status'] == 'complete_reviewed' and report['coverage_gate_passed'], 'target audit failed')
    E.require(E.read(audit / 'verification.json')['status'] == 'complete_reviewed', 'target payloads not reviewed')
    source = Path(plan['value_source'])
    old = E.read(source / 'protocol.json')
    review = E.read(source / 'training-review.json')
    E.require(review['status'] == 'complete_reviewed'
              and review['learning_completion_sha256'] == E.sha(source / 'learning/completion.json'), 'warm value source changed')
    E.require(plan['input_columns'] == old['input_columns']
              and plan['learning_source'] == old['learning_source'], 'public state input changed')
    return plan


class Data:
    def __init__(self, store, plan):
        self.store = store
        self.value = V.Data(store, Path(plan['value_source']) / 'data', plan['input_columns'])
        source = Path(plan['paired_source']) / 'data'
        E.proof(source, 'completion.json')
        self.rows = E.read(source / 'rows.json')
        self.pairs = np.load(source / 'pairs.npy', allow_pickle=False)
        target = Path(plan['target_source']) / 'data'
        E.proof(target, 'completion.json')
        self.first = np.load(target / 'first_combat.npy', allow_pickle=False)
        combat = Path(plan['combat_source']) / 'data'
        E.proof(combat, 'completion.json')
        self.targets = np.load(combat / 'targets.npy', allow_pickle=False)
        self.combat_seeds = np.load(combat / 'seed.npy', allow_pickle=False)
        self.menu_pairs = {i: [] for i in range(len(self.rows))}
        for i, (row_id, candidate) in enumerate(self.pairs):
            row = self.rows[row_id]
            states = [row['successors'][candidate], row['successors'][row['parent']]]
            if bool((self.first[states] >= 0).all()):
                self.menu_pairs[row_id].append(i)
        self.by_seed = {f['seed']: [] for f in store.families}
        for i, row in enumerate(self.rows):
            if self.menu_pairs[i]: self.by_seed[row['seed']].append(i)
        E.require(all(self.by_seed.values()) and sum(map(len, self.menu_pairs.values())) == 18682,
                  'admitted auxiliary pair scope changed')

    def sample(self, families, uniforms):
        result = []
        for a, b, c in uniforms:
            family = families[min(int(a*len(families)), len(families)-1)]
            menus = self.by_seed[family['seed']]
            pairs = self.menu_pairs[menus[min(int(b*len(menus)), len(menus)-1)]]
            result.append(pairs[min(int(c*len(pairs)), len(pairs)-1)])
        return np.array(result, dtype=np.int64)

    def state_ids(self, pair_ids):
        E.require(len(pair_ids) > 0 and bool(((pair_ids >= 0) & (pair_ids < len(self.pairs))).all()), 'invalid combat pair ids')
        alternatives, parents = [], []
        for pair_id in pair_ids:
            row_id, candidate = self.pairs[pair_id]
            row = self.rows[row_id]
            alternatives.append(row['successors'][candidate])
            parents.append(row['successors'][row['parent']])
        return np.array(alternatives+parents, dtype=np.int64)

    def batch(self, pair_ids, allowed):
        ids = self.state_ids(pair_ids)
        # Check true state ownership before looking up combat outcome labels.
        features, _ = self.value.batch(ids, allowed)
        indices = self.first[ids]
        E.require(bool((indices >= 0).all()), 'missing mapped-combat endpoint')
        owners = self.value.seeds[np.searchsorted(self.value.ends, ids, side='right')]
        E.require(np.array_equal(self.combat_seeds[indices], owners), 'combat labels crossed family')
        return features, torch.from_numpy(self.targets[indices])


def warm_model(source, width, fold, inner):
    model = A.warm_model(source, width, fold, inner)
    heart_head = {k: v.clone() for k, v in model.tail[-1].state_dict().items()}
    model.tail[-1] = torch.nn.Linear(64, 2)
    torch.nn.init.zeros_(model.tail[-1].weight); torch.nn.init.zeros_(model.tail[-1].bias)
    return model, heart_head


def differences(values):
    E.require(values.ndim == 2 and values.shape[1] == 2 and len(values) > 0 and len(values) % 2 == 0,
              'invalid combat outcome matrix')
    n = len(values)//2
    return values[:n]-values[n:]


def fit(model, data, families, steps, fold, checkpoint=None):
    optimizer = torch.optim.AdamW(model.parameters(), lr=RECIPE['learning_rate'], weight_decay=RECIPE['weight_decay'])
    rng = np.random.default_rng(RECIPE['seed']+fold)
    allowed = {f['seed'] for f in families}
    if checkpoint: checkpoint(0, model)
    for step in range(1, steps+1):
        ids = data.sample(families, rng.random((RECIPE['batch_size'], 3)))
        features, labels = data.batch(ids, allowed)
        loss = (differences(model(features))-differences(labels)).square().mean()
        O.gradient_step(loss, optimizer, model, RECIPE['gradient_norm'])
        if checkpoint and step in RECIPE['checkpoints']: checkpoint(step, model)


def mse(model, data, ids, allowed):
    total, baseline = np.zeros(2), np.zeros(2)
    with torch.inference_mode():
        for at in range(0, len(ids), 128):
            features, labels = data.batch(ids[at:at+128], allowed)
            target = differences(labels)
            total += (differences(model(features))-target).square().sum(dim=0).numpy()
            baseline += target.square().sum(dim=0).numpy()
    return (total/len(ids)).tolist(), (baseline/len(ids)).tolist()


def train(root):
    plan = registered(root)
    checked = E.read(root / 'data-review.json')
    E.require(checked['status'] == 'complete_reviewed'
              and checked['target_completion_sha256'] == E.sha(Path(plan['target_source']) / 'data/completion.json'), 'auxiliary data not reviewed')
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store'); data = Data(store, plan)
    source = Path(plan['value_source']); width = store.spec['width']+store.spec['descriptor_dim']
    out = root / 'learning'; out.mkdir(); reports = []
    for fold in range(3):
        fit_families = [f for f in store.families if O.T.fold(f['seed']) != fold]
        held = [f for f in store.families if O.T.fold(f['seed']) == fold]
        inner, valid = O.inner_partition(fit_families)
        old_roles = E.read(source / 'learning' / f'fold-{fold}/roles.json')
        roles = dict(inner_train=[f['seed'] for f in inner], inner_validation=[f['seed'] for f in valid],
                     fit=[f['seed'] for f in fit_families], held=[f['seed'] for f in held])
        E.require(all(roles[k] == old_roles[k] for k in roles), 'auxiliary warm roles changed')
        rng = np.random.default_rng(RECIPE['seed']+2000+fold)
        roles['validation_pairs'] = data.sample(valid, rng.random((RECIPE['validation_draws'], 3))).tolist()
        roles['held_pairs'] = data.sample(held, rng.random((RECIPE['validation_draws'], 3))).tolist()
        directory = out / f'fold-{fold}'; directory.mkdir(); E.write(directory / 'roles.json', roles)
        model, _ = warm_model(source, width, fold, True); curve = []
        def checkpoint(step, current):
            error, base = mse(current, data, np.array(roles['validation_pairs']), set(roles['inner_validation']))
            curve.append(dict(step=step, mse=error, zero_baseline_mse=base, mean_mse=float(np.mean(error))))
            torch.save(current.state_dict(), directory / f'inner-{step}.pt')
        fit(model, data, inner, RECIPE['steps'], fold, checkpoint)
        selected = min(curve, key=lambda r: (r['mean_mse'], r['step']))['step']
        model, heart_head = warm_model(source, width, fold, False)
        fit(model, data, fit_families, selected, fold)
        torch.save(dict(model_type='card_combat_delta_auxiliary', prediction_only=True,
            model_state=model.state_dict(), retained_heart_head=heart_head, feature_spec=store.spec,
            input_columns=plan['input_columns'], paired_width=width,
            provenance=dict(fold=fold, fit_families=roles['fit'], selected_steps=selected, recipe=RECIPE,
                value_sha256=E.sha(source / 'learning' / f'fold-{fold}/value.pt'))), directory / 'auxiliary.pt')
        error, base = mse(model, data, np.array(roles['held_pairs']), set(roles['held']))
        report = dict(fold=fold, selected_steps=selected, held_mse=error, zero_baseline_mse=base)
        E.write(directory / 'stopping.json', curve); E.write(directory / 'report.json', report)
        reports.append(report); print(report, flush=True)
    error = float(np.mean([r['held_mse'] for r in reports]))
    baseline = float(np.mean([r['zero_baseline_mse'] for r in reports]))
    passed = error <= RECIPE['relative_mse_gate']*baseline and all(np.mean(r['held_mse']) < np.mean(r['zero_baseline_mse']) for r in reports)
    E.write(out / 'report.json', dict(status='complete', experiment='E178', folds=reports, held_mse=error,
        zero_baseline_mse=baseline, auxiliary_gate_passed=bool(passed),
        auxiliary_optimizer_updates=3*RECIPE['steps']+sum(r['selected_steps'] for r in reports),
        heart_optimizer_updates=0, new_games=0, policy_adoption=False,
        limits='Auxiliary differences at the first subsequent audited mapped combat, not next-physical-fight, Heart policy, or unseen win rate. No deployment or automatic Heart fitting.'))
    E.write(out / 'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('train', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'train': train, 'check': registered}[args.command](args.study.resolve())
