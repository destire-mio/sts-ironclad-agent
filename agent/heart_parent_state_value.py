"""Direct fixed-parent Heart value learning from admitted public states.

This produces a state predictor, not an action policy. No future observation,
recorded successor lookup or hindsight maximum may be used at deployment.
"""
import argparse
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as NN

import heart_combat_pretraining as P

I, O, E = P.I, P.O, P.E
RECIPE = dict(steps=5000, batch_size=128, learning_rate=.0003, weight_decay=.0001,
    gradient_norm=1., validation_draws=8192, seed=2026092269,
    checkpoints=[0, 250, 500, 1000, 2000, 5000], relative_brier_gate=.9)


def input_columns(spec, auxiliary_columns):
    excluded = set(auxiliary_columns)
    return [i for i in range(spec['state_width']) if i not in excluded]


def state_features(store, ids, columns):
    source = store.shared.take(ids)
    width = store.spec['width']+store.spec['descriptor_dim']
    permitted = torch.zeros(width, dtype=torch.bool)
    permitted[columns] = True
    keep = permitted[source.indices()[1]]
    return torch.sparse_coo_tensor(source.indices()[:, keep], source.values()[keep],
        (len(ids), width), check_invariants=True).coalesce()


def baseline_cells(scalars):
    # Columns: normalized currentHP,maxHP,act,mapY+1,deck size.
    E.require(np.isfinite(scalars).all() and np.all(scalars[:, 1] > 0), 'invalid public scalars')
    act = np.rint(scalars[:, 2]*4).astype(np.int64)-1
    E.require(bool(np.isin(act, range(4)).all()), 'invalid public act')
    row = np.rint(scalars[:, 3]*15).astype(np.int64)-1
    stage = np.clip((row+1)//4, 0, 3)
    hp = np.clip((scalars[:, 0]/scalars[:, 1]*4).astype(np.int64), 0, 3)
    size = np.rint(scalars[:, 4]*100).astype(np.int64)
    deck = np.searchsorted([16, 26, 36], size, side='right')
    return (((act*4+stage)*4+hp)*4+deck).astype(np.uint8)


def registered(root):
    reg = E.read(root / 'registration.json')
    E.require(reg['runner_sha256'] == E.sha(__file__), 'parent-value runner changed')
    for path, digest in reg['hashes'].items():
        E.require(E.sha(path) == digest, 'bound source changed: '+path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['recipe'] == RECIPE and plan['new_training_rollouts'] == 0, 'recipe changed')
    source = Path(plan['encoder_source'])
    accepted = E.read(source / 'auxiliary-review.json')
    E.require(accepted['status'] == 'complete_reviewed' and accepted['passed'], 'encoder not admitted')
    E.require(accepted['learning_completion_sha256'] == E.sha(source / 'learning/completion.json'), 'encoder completion differs')
    audited = E.read(Path(plan['target_audit']))
    E.require(audited['status'] == 'complete_reviewed' and audited['state_targets'] == 2039965,
              'fixed-parent labels not reviewed')
    spec = E.read(Path(plan['learning_source']) / 'store/metadata.json')['spec']
    dropped = E.read(source / 'protocol.json')['masked_columns']
    E.require(plan['input_columns'] == input_columns(spec, dropped), 'public value input changed')
    return plan


def prepare(root):
    plan = registered(root)
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    targets = exact['parent_value'].astype(np.float32)
    E.require(len(targets) == store.states and bool(np.isin(targets, [0., 1.]).all()), 'invalid state targets')
    edges = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    E.require(len(edges) == store.states and len(np.unique(store.edge_state[edges])) == store.states, 'missing parent action')
    E.require(bool(np.array_equal(targets[store.edge_state[edges]],
        np.where(store.done[edges], store.reward[edges], targets[store.next_state[edges]]))), 'parent return recursion differs')
    scalars = np.zeros((store.states, 5), dtype=np.float32)
    for j, raw in enumerate([0, 1, 4, 7, 8]):
        column = store.spec['observations'].index(raw)
        positions = np.flatnonzero(store.shared.cols == column)
        rows = np.searchsorted(store.shared.ptr, positions, side='right')-1
        scalars[rows, j] = store.shared.values[positions]
    cells = baseline_cells(scalars)
    out = root / 'data'; out.mkdir()
    np.save(out / 'targets.npy', targets, allow_pickle=False)
    np.save(out / 'cells.npy', cells, allow_pickle=False)
    report = dict(status='complete', states=store.states, families=len(store.families),
        winning_labels=int(targets.sum()), losing_labels=int(len(targets)-targets.sum()),
        baseline_cells=256, input_columns=len(plan['input_columns']), new_games=0, optimizer_updates=0)
    E.write(out / 'report.json', report)
    E.write(out / 'completion.json', dict(status='complete', hashes={p.name: E.sha(p) for p in out.iterdir()}))
    print(report, flush=True)


class Data:
    def __init__(self, store, root, columns):
        E.proof(root, 'completion.json')
        self.store, self.columns = store, columns
        self.targets = np.load(root / 'targets.npy', allow_pickle=False)
        self.cells = np.load(root / 'cells.npy', allow_pickle=False)
        self.families = store.families
        self.ends = np.array([f['end'] for f in self.families])
        self.seeds = np.array([f['seed'] for f in self.families], dtype=np.int64)
        E.require(np.array_equal(np.r_[0, self.ends[:-1]], [f['begin'] for f in self.families])
                  and self.ends[-1] == len(self.targets) == len(self.cells), 'state ownership differs')

    @staticmethod
    def sample(families, uniforms):
        rows = []
        for a, b in uniforms:
            family = families[min(int(a*len(families)), len(families)-1)]
            rows.append(family['begin']+min(int(b*(family['end']-family['begin'])), family['end']-family['begin']-1))
        return np.array(rows, dtype=np.int64)

    def batch(self, ids, allowed):
        E.require(bool(((ids >= 0) & (ids < len(self.targets))).all()), 'invalid state row')
        owners = self.seeds[np.searchsorted(self.ends, ids, side='right')]
        E.require(all(int(seed) in allowed for seed in owners), 'held family requested as value fitting label')
        return state_features(self.store, ids, self.columns), torch.from_numpy(self.targets[ids])

    def baseline(self, families):
        sums, counts = np.zeros(256), np.zeros(256)
        for family in families:
            a, b = family['begin'], family['end']
            sums += np.bincount(self.cells[a:b], weights=self.targets[a:b], minlength=256)/(b-a)
            counts += np.bincount(self.cells[a:b], minlength=256)/(b-a)
        overall = sums.sum()/counts.sum()
        return np.where(counts > 0, sums/np.maximum(counts, 1e-12), overall)


def warm_model(source, width, fold, inner):
    directory = source / 'learning' / f'fold-{fold}'
    step = E.read(directory / 'auxiliary-report.json')['selected_steps']
    path = directory / (f'aux-inner-{step}.pt' if inner else 'auxiliary.pt')
    model = P.auxiliary_model(width, fold)
    model.load_state_dict(torch.load(path, weights_only=True, map_location='cpu'))
    model.tail[-1] = torch.nn.Linear(64, 1)
    torch.nn.init.zeros_(model.tail[-1].weight)
    torch.nn.init.zeros_(model.tail[-1].bias)
    return model


def brier(model, data, ids, allowed):
    total = 0.
    with torch.inference_mode():
        for at in range(0, len(ids), 128):
            features, labels = data.batch(ids[at:at+128], allowed)
            prediction = model(features).squeeze(-1).sigmoid()
            total += float((prediction-labels).square().sum())
    return total/len(ids)


def fit(model, data, families, steps, fold, checkpoint=None):
    optimizer = torch.optim.AdamW(model.parameters(), lr=RECIPE['learning_rate'], weight_decay=RECIPE['weight_decay'])
    rng = np.random.default_rng(RECIPE['seed']+fold)
    allowed = {f['seed'] for f in families}
    if checkpoint: checkpoint(0, model)
    for step in range(1, steps+1):
        ids = data.sample(families, rng.random((RECIPE['batch_size'], 2)))
        features, labels = data.batch(ids, allowed)
        loss = NN.binary_cross_entropy_with_logits(model(features).squeeze(-1), labels)
        O.gradient_step(loss, optimizer, model, RECIPE['gradient_norm'])
        if checkpoint and step in RECIPE['checkpoints']: checkpoint(step, model)


def train(root):
    plan = registered(root)
    review = E.read(root / 'data-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['data_completion_sha256'] == E.sha(root / 'data/completion.json'), 'value data not reviewed')
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = Data(store, root / 'data', plan['input_columns'])
    source = Path(plan['encoder_source'])
    out = root / 'learning'; out.mkdir()
    width = store.spec['width']+store.spec['descriptor_dim']
    reports = []
    for fold in range(3):
        families = [f for f in data.families if O.T.fold(f['seed']) != fold]
        held = [f for f in data.families if O.T.fold(f['seed']) == fold]
        inner, valid = O.inner_partition(families)
        roles = E.read(source / 'learning' / f'fold-{fold}/auxiliary-roles.json')
        E.require(roles['inner_train'] == [f['seed'] for f in inner] and roles['inner_validation'] == [f['seed'] for f in valid]
                  and roles['fit'] == [f['seed'] for f in families], 'encoder family roles differ')
        directory = out / f'fold-{fold}'; directory.mkdir()
        rng = np.random.default_rng(RECIPE['seed']+2000+fold)
        validation_ids = data.sample(valid, rng.random((RECIPE['validation_draws'], 2)))
        held_ids = data.sample(held, rng.random((RECIPE['validation_draws'], 2)))
        E.write(directory / 'roles.json', dict(inner_train=[f['seed'] for f in inner], inner_validation=[f['seed'] for f in valid],
            fit=[f['seed'] for f in families], held=[f['seed'] for f in held], validation_ids=validation_ids.tolist(), held_ids=held_ids.tolist()))
        model = warm_model(source, width, fold, True)
        curve = []
        def checkpoint(step, current):
            curve.append(dict(step=step, brier=brier(current, data, validation_ids, {f['seed'] for f in valid})))
            torch.save(current.state_dict(), directory / f'inner-{step}.pt')
        fit(model, data, inner, RECIPE['steps'], fold, checkpoint)
        selected = min(curve, key=lambda r: (r['brier'], r['step']))['step']
        model = warm_model(source, width, fold, False)
        fit(model, data, families, selected, fold)
        torch.save(dict(model_type='parent_heart_state_value', prediction_only=True, model_state=model.state_dict(),
            feature_spec=store.spec, input_columns=plan['input_columns'], paired_width=width,
            provenance=dict(fold=fold, fit_families=[f['seed'] for f in families], selected_steps=selected,
                encoder_sha256=E.sha(source / 'learning' / f'fold-{fold}/auxiliary.pt'), recipe=RECIPE)), directory / 'value.pt')
        table, inner_table = data.baseline(families), data.baseline(inner)
        np.save(directory / 'baseline.npy', table, allow_pickle=False)
        np.save(directory / 'inner-baseline.npy', inner_table, allow_pickle=False)
        report = dict(fold=fold, selected_steps=selected,
            held_brier=brier(model, data, held_ids, {f['seed'] for f in held}),
            baseline_brier=float(np.mean((table[data.cells[held_ids]]-data.targets[held_ids])**2)),
            inner_baseline_brier=float(np.mean((inner_table[data.cells[validation_ids]]-data.targets[validation_ids])**2)))
        E.write(directory / 'stopping.json', curve); E.write(directory / 'report.json', report)
        reports.append(report); print(report, flush=True)
    error = float(np.mean([r['held_brier'] for r in reports]))
    baseline = float(np.mean([r['baseline_brier'] for r in reports]))
    passed = error <= RECIPE['relative_brier_gate']*baseline and all(r['held_brier'] < r['baseline_brier'] for r in reports)
    E.write(out / 'report.json', dict(status='complete', folds=reports, held_brier=error, baseline_brier=baseline,
        prediction_gate_passed=passed, value_optimizer_updates=3*RECIPE['steps']+sum(r['selected_steps'] for r in reports),
        auxiliary_optimizer_updates=0, actor_optimizer_updates=0, new_games=0, policy_adoption=False,
        limits='A fixed-parent state prediction model, not an action policy or unseen win rate. Passing only permits a separate public-effect policy design and verification.'))
    E.write(out / 'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'prepare': prepare, 'train': train, 'check': registered}[args.command](args.study.resolve())
