"""Give the existing state predictor a shared printed-cost representation.

All new features are deterministic functions of the already admitted card
faces and owned relics. They supply an inductive bias, not new observations,
effective combat costs, hand-written card values, or a deployed policy.
"""
import argparse
from pathlib import Path

import numpy as np
import torch

import heart_empty_reward_value as L

E, O, V = L.E, L.O, L.V
VERSION = 'public_printed_cost_relations_v1'
MODEL_TYPE = 'printed_cost_parent_value'
COSTS = (-2, -1, 0, 1, 2, 3, 4)
TYPES = ('ATTACK', 'SKILL', 'POWER', 'CURSE', 'STATUS')
ENERGY = ('MARK_OF_PAIN', 'ECTOPLASM', 'PHILOSOPHERS_STONE', 'RUNIC_DOME',
          'SOZU', 'VELVET_CHOKER', 'BUSTED_CROWN', 'COFFEE_DRIPPER',
          'CURSED_KEY', 'FUSION_HAMMER')
CONTEXTS = ('constant', 'unconditional_energy_bonus_div3', 'snecko_eye_owned',
            'mummified_hand_owned', 'corruption_owned', 'runic_pyramid_owned')
WIDTH = len(COSTS) * len(TYPES) * len(CONTEXTS)


def layout(spec, x, facts):
    E.require(facts['version'] == VERSION and len(facts['faces']) == 2*x.A.CARD_CAP,
              'printed-cost facts differ')
    lookup = {raw: i for i, raw in enumerate(spec['observations'])}
    deck = O.C.D.feature_spec(x)['deck_offset']
    relic = deck + 6*x.A.CARD_CAP + 32
    bins = []
    for i, row in enumerate(facts['faces']):
        E.require(row['id'] == i//2 and row['upgraded'] == bool(i % 2), 'card-face order differs')
        bins.append(-1 if row['type'] not in TYPES or row['printed_cost'] is None else
                    TYPES.index(row['type'])*len(COSTS)+COSTS.index(row['printed_cost']))
    return dict(base_width=spec['width']+spec['descriptor_dim'],
        face_columns=[lookup[deck+i] for i in range(2*x.A.CARD_CAP)], face_bins=bins,
        energy_columns=[lookup[relic+int(getattr(x.R.sts.RelicId, name))] for name in ENERGY],
        relic_columns=[lookup[relic+int(getattr(x.R.sts.RelicId, name))]
                       for name in ('SNECKO_EYE', 'MUMMIFIED_HAND', 'RUNIC_PYRAMID')],
        corruption_columns=[lookup[deck+2*int(x.R.sts.CardId.CORRUPTION)+j] for j in range(2)],
        extra_width=WIDTH, version=VERSION, contexts=list(CONTEXTS), costs=list(COSTS), types=list(TYPES))


class Relations:
    """Sparse printed-cost/type histogram crossed with six public contexts."""
    def __init__(self, shape):
        self.shape = shape
        self.face_bin = torch.full((shape['base_width'],), -1, dtype=torch.long)
        self.face_bin[shape['face_columns']] = torch.tensor(shape['face_bins'])
        self.invalid = torch.zeros(shape['base_width'], dtype=torch.bool)
        self.invalid[shape['face_columns']] = torch.tensor(shape['face_bins']) < 0
        self.context_column = torch.full((shape['base_width'],), -1, dtype=torch.long)
        for column in shape['energy_columns']: self.context_column[column] = 1
        for column, target in zip(shape['relic_columns'], (2, 3, 5)): self.context_column[column] = target
        for column in shape['corruption_columns']: self.context_column[column] = 4

    def values(self, features):
        E.require(features.is_sparse and features.is_coalesced()
                  and features.shape[1] == self.shape['base_width'], 'cost input layout differs')
        rows, cols = features.indices(); amounts = features.values(); batch = features.shape[0]
        E.require(not bool(self.invalid[cols].any()), 'unsupported card face present')
        bins = self.face_bin[cols]; keep = bins >= 0
        histogram = amounts.new_zeros(batch*len(COSTS)*len(TYPES))
        # Counts share a factor 1/20, which cancels in the deck fractions.
        histogram.index_add_(0, rows[keep]*len(COSTS)*len(TYPES)+bins[keep], amounts[keep])
        histogram = histogram.reshape(batch, -1)
        E.require(bool((histogram.sum(1) > 0).all()), 'empty public deck')
        histogram = histogram / histogram.sum(1, keepdim=True)
        contexts = amounts.new_zeros(batch*len(CONTEXTS))
        targets = self.context_column[cols]; keep = targets >= 0
        contexts.index_add_(0, rows[keep]*len(CONTEXTS)+targets[keep], amounts[keep])
        contexts = contexts.reshape(batch, -1)
        contexts[:, 0] = 1.; contexts[:, 1] /= 3.
        contexts[:, 4] = (contexts[:, 4] > 0).to(amounts.dtype)
        return (contexts[:, :, None]*histogram[:, None, :]).flatten(1)

    def append(self, features):
        extra = self.values(features).to_sparse().coalesce()
        indices = extra.indices().clone(); indices[1] += features.shape[1]
        return torch.sparse_coo_tensor(torch.cat((features.indices(), indices), 1),
            torch.cat((features.values(), extra.values())),
            (features.shape[0], features.shape[1]+WIDTH), check_invariants=True).coalesce()


class Data(L.Data):
    def __init__(self, store, root, columns, shape):
        super().__init__(store, root, columns)
        self.relations = Relations(shape)

    def batch(self, ids, allowed):
        features, labels = super().batch(ids, allowed)
        return self.relations.append(features), labels


def warm_model(source, base_width, fold, inner):
    model = V.warm_model(source, base_width, fold, inner)
    weight, bias = model.input.weight.detach().clone(), model.input.bias.detach().clone()
    model.input = torch.nn.Linear(base_width+WIDTH, weight.shape[0])
    with torch.no_grad():
        model.input.weight.zero_(); model.input.weight[:, :base_width].copy_(weight)
        model.input.bias.copy_(bias)
    return model


def registered(root):
    registration = E.read(root/'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'cost runner changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound source changed: '+path)
    plan = E.read(root/'protocol.json'); control = Path(plan['preceding_study'])
    # Validate the control's actual frozen files. Calling an imported runner's
    # registered(control) would compare a different snapshot's __file__ hash.
    old_registration = E.read(control/'registration.json')
    E.require(old_registration['runner_sha256'] == E.sha(control/'program/heart_empty_reward_value.py'),
              'control runner changed')
    for path, digest in old_registration['hashes'].items():
        E.require(E.sha(path) == digest, 'control source changed: '+path)
    old = E.read(control/'protocol.json'); review = E.read(control/'training-review.json')
    E.require(old['experiment'] == 'E185', 'wrong cost control')
    E.require(plan['experiment'] == 'E187' and plan['feature_version'] == VERSION
              and plan['recipe'] == V.EXTENDED_RECIPE and plan['new_training_rollouts'] == 0,
              'unregistered cost recipe')
    E.require(review['status'] == 'complete_reviewed' and not review['eligible_for_policy_design']
              and review['learning_completion_sha256'] == E.sha(control/'learning/completion.json'),
              'control learning not reviewed')
    for key in ('learning_source', 'diagnosis', 'encoder_source', 'runtime', 'natural_source', 'input_columns', 'recipe'):
        E.require(plan[key] == old[key], 'cost control changed '+key)
    E.require((root/'data').resolve() == (control/'data').resolve(), 'cost control must reuse admitted data')
    return plan


def train(root):
    plan = registered(root); recipe = plan['recipe']; review = E.read(root/'data-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['data_completion_sha256'] == E.sha(root/'data/completion.json'),
              'cost data not reviewed')
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source'])/'store'); shape = E.read(root/'layout.json')
    x = O.C.D.runtime(plan['runtime'])
    E.require(shape == layout(store.spec, x, E.read(root/'card-facts.json')), 'cost projection differs')
    data = Data(store, root/'data', plan['input_columns'], shape)
    source = Path(plan['encoder_source']); control = Path(plan['preceding_study'])
    out = root/'learning'; out.mkdir(); base_width = shape['base_width']; reports = []
    for fold in range(3):
        families = [f for f in data.families if O.T.fold(f['seed']) != fold]
        held = [f for f in data.families if O.T.fold(f['seed']) == fold]
        inner, valid = O.inner_partition(families)
        rng = np.random.default_rng(recipe['seed']+2000+fold)
        validation_ids = data.sample(valid, rng.random((recipe['validation_draws'], 2)))
        held_ids = data.sample(held, rng.random((recipe['validation_draws'], 2)))
        roles = dict(inner_train=[f['seed'] for f in inner], inner_validation=[f['seed'] for f in valid],
                     fit=[f['seed'] for f in families], held=[f['seed'] for f in held],
                     validation_ids=validation_ids.tolist(), held_ids=held_ids.tolist())
        E.require(roles == E.read(control/'learning'/f'fold-{fold}/roles.json'), 'cost roles or draws changed')
        directory = out/f'fold-{fold}'; directory.mkdir(); E.write(directory/'roles.json', roles)
        model = warm_model(source, base_width, fold, True); curve = []
        def checkpoint(step, current):
            curve.append(dict(step=step, brier=V.brier(current, data, validation_ids, set(roles['inner_validation']))))
            torch.save(current.state_dict(), directory/f'inner-{step}.pt')
        V.fit(model, data, inner, recipe['steps'], fold, checkpoint, recipe)
        selected = min(curve, key=lambda row: (row['brier'], row['step']))['step']
        model = warm_model(source, base_width, fold, False)
        V.fit(model, data, families, selected, fold, recipe=recipe)
        torch.save(dict(model_type=MODEL_TYPE, prediction_only=True, model_state=model.state_dict(),
            feature_spec=store.spec, input_columns=plan['input_columns'], paired_width=base_width+WIDTH,
            normalization=L.VERSION, cost_layout=shape, card_facts_sha256=E.sha(root/'card-facts.json'),
            provenance=dict(fold=fold, fit_families=roles['fit'], selected_steps=selected, recipe=recipe,
                            encoder_sha256=E.sha(source/'learning'/f'fold-{fold}/auxiliary.pt'))), directory/'value.pt')
        table, inner_table = data.baseline(families), data.baseline(inner)
        for name, values in (('baseline', table), ('inner-baseline', inner_table)):
            np.testing.assert_array_equal(values, np.load(control/'learning'/f'fold-{fold}'/(name+'.npy')))
            np.save(directory/(name+'.npy'), values, allow_pickle=False)
        report = dict(fold=fold, selected_steps=selected,
            held_brier=V.brier(model, data, held_ids, set(roles['held'])),
            baseline_brier=float(np.mean((table[data.cells[held_ids]]-data.targets[held_ids])**2)))
        E.write(directory/'stopping.json', curve); E.write(directory/'report.json', report)
        reports.append(report); print(report, flush=True)
    error = float(np.mean([r['held_brier'] for r in reports])); baseline = float(np.mean([r['baseline_brier'] for r in reports]))
    passed = error <= recipe['relative_brier_gate']*baseline and all(r['held_brier'] < r['baseline_brier'] for r in reports)
    E.write(out/'report.json', dict(status='complete', experiment=plan['experiment'], folds=reports,
        held_brier=error, baseline_brier=baseline, prediction_gate_passed=passed,
        value_optimizer_updates=3*recipe['steps']+sum(r['selected_steps'] for r in reports),
        auxiliary_optimizer_updates=0, actor_optimizer_updates=0, new_games=0, policy_adoption=False,
        trainable_parameters=sum(p.numel() for p in model.parameters() if p.requires_grad),
        normalization=L.VERSION, feature_version=VERSION, derived_features=WIDTH,
        limits='Derived printed costs are not effective combat costs. No action policy or unseen success claim.'))
    E.write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('command', choices=('train', 'check'))
    parser.add_argument('--study', required=True, type=Path); args = parser.parse_args()
    {'train': train, 'check': registered}[args.command](args.study.resolve())
