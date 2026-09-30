"""Predict where the fixed parent terminates; decisions still value Heart only.

Failure stage is a supervised outcome, never a public input or progress reward.
The five-category likelihood retains information discarded by binary labels.
"""
import argparse
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as NN

import heart_parent_state_value as V

E, O = V.E, V.O
RECIPE = V.EXTENDED_RECIPE
CATEGORIES = ['non_heart_Act1', 'non_heart_Act2', 'non_heart_Act3_including_act3_only',
              'non_heart_Act4', 'Heart']


def masked_logits(logits, acts):
    E.require(logits.ndim == 2 and logits.shape[1] == 5 and len(acts) == len(logits), 'terminal output shape differs')
    E.require(bool(((acts >= 1) & (acts <= 4)).all()), 'invalid public current act')
    earlier = torch.arange(5, device=logits.device)[None, :] < acts[:, None]-1
    return logits.masked_fill(earlier, float('-inf'))


def heart_probability(logits, acts):
    return masked_logits(logits, acts).softmax(dim=1)[:, 4]


def terminal_loss(logits, categories, acts):
    E.require(bool(((categories >= acts-1) & (categories <= 4)).all()), 'impossible terminal category')
    return NN.cross_entropy(masked_logits(logits, acts), categories)


class Data(V.Data):
    def __init__(self, store, root, columns):
        super().__init__(store, root, columns)
        self.categories = np.load(root / 'terminal_categories.npy', allow_pickle=False)
        self.acts = np.load(root / 'acts.npy', allow_pickle=False)
        E.require(len(self.categories) == len(self.acts) == len(self.targets), 'terminal data rows differ')
        E.require(bool(np.isin(self.acts, [1, 2, 3, 4]).all()), 'invalid current act')
        E.require(bool(((self.categories >= self.acts-1) & (self.categories <= 4)).all()), 'impossible category label')
        E.require(np.array_equal(self.categories == 4, self.targets == 1), 'Heart target changed')

    def batch(self, ids, allowed):
        features, _ = super().batch(ids, allowed)
        return features, torch.from_numpy(self.categories[ids].astype(np.int64)), torch.from_numpy(self.acts[ids].astype(np.int64))


def warm_model(source, width, fold, inner):
    model = V.warm_model(source, width, fold, inner)
    model.tail[-1] = torch.nn.Linear(64, 5)
    torch.nn.init.zeros_(model.tail[-1].weight)
    torch.nn.init.zeros_(model.tail[-1].bias)
    E.require(all(p.requires_grad for p in model.parameters()), 'unexpected encoder freeze')
    return model


def brier(model, data, ids, allowed):
    total = 0.
    with torch.inference_mode():
        for at in range(0, len(ids), 128):
            features, categories, acts = data.batch(ids[at:at+128], allowed)
            prediction = heart_probability(model(features), acts)
            total += float((prediction-(categories == 4).to(prediction.dtype)).square().sum())
    return total/len(ids)


def fit(model, data, families, steps, fold, checkpoint=None):
    optimizer = torch.optim.AdamW(model.parameters(), lr=RECIPE['learning_rate'], weight_decay=RECIPE['weight_decay'])
    rng = np.random.default_rng(RECIPE['seed']+fold)
    allowed = {f['seed'] for f in families}
    if checkpoint: checkpoint(0, model)
    for step in range(1, steps+1):
        ids = data.sample(families, rng.random((RECIPE['batch_size'], 2)))
        features, categories, acts = data.batch(ids, allowed)
        loss = terminal_loss(model(features), categories, acts)
        O.gradient_step(loss, optimizer, model, RECIPE['gradient_norm'])
        if checkpoint and step in RECIPE['checkpoints']: checkpoint(step, model)


def registered(root):
    reg = E.read(root / 'registration.json')
    E.require(reg['runner_sha256'] == E.sha(__file__), 'terminal-stage runner changed')
    for path, digest in reg['hashes'].items():
        E.require(E.sha(path) == digest, 'bound source changed: '+path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['experiment'] == 'E174' and plan['recipe'] == RECIPE and plan['categories'] == CATEGORIES,
              'terminal-stage recipe changed')
    E.require(plan['new_training_rollouts'] == 0, 'no new training game budget')
    previous = Path(plan['control_source'])
    control = E.read(previous / 'training-review.json')
    E.require(control['status'] == 'complete_reviewed' and not control['prediction_gate_passed'], 'missing reviewed binary control')
    E.require(control['learning_completion_sha256'] == E.sha(previous / 'learning/completion.json'), 'binary control changed')
    old = E.read(previous / 'protocol.json')
    for key in ('recipe', 'learning_source', 'diagnosis', 'encoder_source', 'runtime', 'natural_source', 'input_columns'):
        E.require(plan[key] == old[key], 'terminal objective changed control '+key)
    source = Path(plan['encoder_source'])
    accepted = E.read(source / 'auxiliary-review.json')
    E.require(accepted['status'] == 'complete_reviewed' and accepted['passed'], 'encoder not admitted')
    E.require(accepted['learning_completion_sha256'] == E.sha(source / 'learning/completion.json'), 'encoder source changed')
    data_root = Path(plan['data_source']) / 'data'
    E.proof(data_root, 'completion.json')
    audited = E.read(data_root / 'report.json')
    E.require(audited['status'] == 'complete_reviewed' and audited['states'] == 2039965 and
              audited['routes'] == 29759 and audited['all_heart_labels_equal_original'] and
              audited['all_parent_category_recursions_verified'], 'terminal labels not admitted')
    E.require((root / 'data').resolve() == data_root.resolve(), 'terminal data reference differs')
    spec = E.read(Path(plan['learning_source']) / 'store/metadata.json')['spec']
    dropped = E.read(source / 'protocol.json')['masked_columns']
    E.require(plan['input_columns'] == V.input_columns(spec, dropped), 'public inputs changed')
    return plan


def train(root):
    plan = registered(root)
    review = E.read(root / 'data-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['data_completion_sha256'] == E.sha(root / 'data/completion.json'),
              'terminal input and loss not reviewed')
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
        torch.save(dict(model_type='parent_terminal_stage_value', prediction_only=True, model_state=model.state_dict(),
            feature_spec=store.spec, input_columns=plan['input_columns'], paired_width=width, categories=CATEGORIES,
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
        trainable_parameters=sum(p.numel() for p in model.parameters()), categories=CATEGORIES,
        limits='Terminal type is extra supervision; only Heart probability selects stopping and measures prediction. No floor reward, action policy or unseen win-rate claim.'))
    E.write(out / 'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('train', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'train': train, 'check': registered}[args.command](args.study.resolve())
