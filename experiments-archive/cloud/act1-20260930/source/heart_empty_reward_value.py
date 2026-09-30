"""Train the existing parent-value predictor with empty-reward invariance.

Normalization reads the current public menu and the frozen parent's choice.
Recorded successors verify its equivalence but are never inference inputs.
"""
import argparse
from pathlib import Path

import numpy as np
import torch

import heart_parent_state_value as V

E, O = V.E, V.O
VERSION = 'empty_normal_combat_reward_to_map_v1'


def empty_reward(screen_is_reward, room_is_normal_combat, kinds, parent_kind,
                 skip, drink, discard):
    return bool(screen_is_reward and room_is_normal_combat and len(kinds)
                and parent_kind == skip and all(k in (skip, drink, discard) for k in kinds))


def normalize(features, flags, reward_column, map_column):
    """Rewrite two public screen bits without changing the source tensor."""
    E.require(features.is_sparse and features.is_coalesced(), 'coalesced sparse input required')
    flags = torch.as_tensor(flags, dtype=torch.bool)
    E.require(flags.shape == (features.shape[0],), 'screen flag shape differs')
    index, values = features.indices(), features.values()
    remove = flags[index[0]] & ((index[1] == reward_column) | (index[1] == map_column))
    rows = torch.nonzero(flags).flatten()
    added = torch.stack((rows, torch.full_like(rows, map_column)))
    return torch.sparse_coo_tensor(torch.cat((index[:, ~remove], added), 1),
        torch.cat((values[~remove], values.new_ones(len(rows)))), features.shape,
        check_invariants=True).coalesce()


def layout(store, x):
    lookup = {raw: i for i, raw in enumerate(store.spec['observations'])}
    return dict(reward_column=lookup[55+int(x.R.sts.ScreenState.REWARDS)],
                map_column=lookup[55+int(x.R.sts.ScreenState.MAP_SCREEN)],
                room_columns=[lookup[35+int(room)] for room in (x.R.sts.Room.MONSTER, x.R.sts.Room.ELITE)],
                screen_columns=[lookup[k] for k in range(55, 65)])


def public_flags(store, x):
    shape = layout(store, x)
    kinds = store.descriptors.cols[store.descriptors.ptr[:-1]]
    E.require(bool(((kinds >= 0) & (kinds < 24)).all()) and
              bool((store.descriptors.values[store.descriptors.ptr[:-1]] == 1).all()), 'action kind layout changed')
    eligible_kind = np.isin(kinds, [x.A.AK_REWARD_SKIP, x.A.AK_POTION_DRINK, x.A.AK_POTION_DISCARD])
    flags = np.logical_and.reduceat(eligible_kind, store.menu_ptr[:-1])
    flags &= kinds[store.parent] == x.A.AK_REWARD_SKIP

    def present(column):
        positions = np.flatnonzero(store.shared.cols == column)
        E.require(bool((store.shared.values[positions] == 1).all()), 'screen/room is not one-hot')
        present = np.zeros(store.states, dtype=bool)
        present[np.searchsorted(store.shared.ptr, positions, side='right')-1] = True
        return present

    flags &= present(shape['reward_column'])
    flags &= present(shape['room_columns'][0]) | present(shape['room_columns'][1])
    return flags, shape


def registered(root):
    registration = E.read(root/'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'invariance runner changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound source changed: '+path)
    plan = E.read(root/'protocol.json')
    E.require(plan['experiment'] in ('E185', 'E186') and plan['recipe'] == V.EXTENDED_RECIPE
              and plan['new_training_rollouts'] == 0 and plan['normalization'] == VERSION, 'recipe differs')
    source = Path(plan['preceding_study']); old = V.registered(source)
    for key in ('learning_source', 'diagnosis', 'encoder_source', 'runtime', 'natural_source'):
        E.require(plan[key] == old[key], 'control changed '+key)
    if plan['experiment'] == 'E185':
        E.require(plan['input_columns'] == old['input_columns'], 'normalization control changed its public columns')
    else:
        spec = E.read(Path(plan['learning_source'])/'store/metadata.json')['spec']
        E.require(plan['input_columns'] == list(range(spec['state_width'])), 'full public observation differs')
        previous = Path(plan['normalization_study'])
        review = E.read(previous/'training-review.json')
        E.require(review['status'] == 'complete_reviewed' and not review['eligible_for_policy_design']
                  and review['learning_completion_sha256'] == E.sha(previous/'learning/completion.json'),
                  'normalization learning evidence differs')
        E.require((root/'data').resolve() == (previous/'data').resolve(), 'full-input control must reuse the admitted rows')
    review = E.read(source/'training-review.json')
    E.require(review['status'] == 'complete_reviewed' and not review['prediction_gate_passed'], 'preceding result differs')
    E.require(review['learning_completion_sha256'] == E.sha(source/'learning/completion.json'), 'preceding proof differs')
    evidence = E.read(Path(plan['mechanism_evidence'])/'result.json')
    E.require(evidence['status'] == 'complete_reviewed' and evidence['contracted_successors'] == 18750
              and evidence['initial']['canonical_wins'] == evidence['initial']['raw_wins'] == 144,
              'mechanism evidence or negative diagnostic outcome changed')
    return plan


def prepare(root):
    plan = registered(root); source = Path(plan['preceding_study'])
    store = O.Store(Path(plan['learning_source'])/'store')
    data = V.Data(store, source/'data', plan['input_columns'])
    x = O.C.D.runtime(plan['runtime']); flags, shape = public_flags(store, x)
    E.require(shape['reward_column'] in data.columns and shape['map_column'] in data.columns, 'screen input absent')
    parent_edges = np.full(store.states, -1, dtype=np.int64)
    edges = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    E.require(len(edges) == store.states and len(np.unique(store.edge_state[edges])) == store.states, 'parent edge missing')
    parent_edges[store.edge_state[edges]] = edges
    selected = np.flatnonzero(flags); following = store.next_state[parent_edges[selected]]
    E.require(not bool(store.done[parent_edges[selected]].any()), 'terminal normalization')
    E.require(np.array_equal(data.targets[selected], data.targets[following]), 'normalization changes return')
    # Compare the entire admitted public observation, not only the learner's
    # retained columns. Menus legitimately change on a reward-to-map exit.
    def row(state):
        a, b = store.shared.ptr[state:state+2]
        c, v = store.shared.cols[a:b], store.shared.values[a:b]
        mask = c < store.spec['state_width']
        return c[mask], v[mask]
    for i, (before, after) in enumerate(zip(selected, following)):
        a, av = row(before); b, bv = row(after)
        E.require(av[a == shape['reward_column']].tolist() == [1.]
                  and bv[b == shape['map_column']].tolist() == [1.], 'normalization is not a map exit')
        ka = ~np.isin(a, shape['screen_columns']); kb = ~np.isin(b, shape['screen_columns'])
        E.require(np.array_equal(a[ka], b[kb]) and np.array_equal(av[ka], bv[kb]), 'normalization changes public resources')
        if (i+1) % 100000 == 0: print(dict(stage='equivalence', checked=i+1), flush=True)
    E.require(np.array_equal(flags[following], np.zeros(len(following), dtype=bool)), 'normalization not idempotent')
    out = root/'data'; out.mkdir()
    np.save(out/'flags.npy', flags, allow_pickle=False)
    np.save(out/'exit_states.npy', selected, allow_pickle=False)
    np.save(out/'exit_successors.npy', following, allow_pickle=False)
    for name in ('targets.npy', 'cells.npy'):
        (out/name).write_bytes((source/'data'/name).read_bytes())
    E.write(out/'layout.json', shape)
    E.write(out/'report.json', dict(status='complete', states=store.states, families=len(store.families),
        normalized_states=len(selected), return_and_public_equivalence_verified=True,
        normalization_from_current_public_menu_and_parent=True, new_games=0, optimizer_updates=0))
    E.write(out/'completion.json', dict(status='complete', hashes={p.name: E.sha(p) for p in out.iterdir()}))
    print(E.read(out/'report.json'), flush=True)


class Data(V.Data):
    def __init__(self, store, root, columns):
        super().__init__(store, root, columns)
        self.flags = np.load(root/'flags.npy', allow_pickle=False)
        self.layout = E.read(root/'layout.json')
        E.require(self.flags.dtype == np.bool_ and self.flags.shape == (store.states,), 'normalization flags differ')

    def batch(self, ids, allowed):
        features, labels = super().batch(ids, allowed)
        return normalize(features, self.flags[ids], self.layout['reward_column'], self.layout['map_column']), labels


def train(root):
    plan = registered(root); recipe = plan['recipe']
    review = E.read(root/'data-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['data_completion_sha256'] == E.sha(root/'data/completion.json'),
              'data/preflight not reviewed')
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source'])/'store'); data = Data(store, root/'data', plan['input_columns'])
    source = Path(plan['encoder_source']); control = Path(plan['preceding_study'])
    out = root/'learning'; out.mkdir(); width = store.spec['width']+store.spec['descriptor_dim']; reports = []
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
        E.require(roles == E.read(control/'learning'/f'fold-{fold}/roles.json'), 'matched state draws or roles changed')
        directory = out/f'fold-{fold}'; directory.mkdir(); E.write(directory/'roles.json', roles)
        model = V.warm_model(source, width, fold, True); curve = []
        def checkpoint(step, current):
            curve.append(dict(step=step, brier=V.brier(current, data, validation_ids, set(roles['inner_validation']))))
            torch.save(current.state_dict(), directory/f'inner-{step}.pt')
        V.fit(model, data, inner, recipe['steps'], fold, checkpoint, recipe)
        selected = min(curve, key=lambda row: (row['brier'], row['step']))['step']
        model = V.warm_model(source, width, fold, False)
        V.fit(model, data, families, selected, fold, recipe=recipe)
        torch.save(dict(model_type='empty_reward_parent_value', prediction_only=True, model_state=model.state_dict(),
            feature_spec=store.spec, input_columns=plan['input_columns'], paired_width=width, normalization=VERSION,
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
        normalization=VERSION, limits='Predictor experiment; unchanged prior failed gates and no action policy or unseen success claim.'))
    E.write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('command', choices=('prepare', 'train', 'check'))
    parser.add_argument('--study', required=True, type=Path); args = parser.parse_args()
    {'prepare': prepare, 'train': train, 'check': registered}[args.command](args.study.resolve())
