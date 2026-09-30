"""Learn recorded combat consequences before fitting Heart action improvements.

Auxiliary labels never become rewards or policy inputs. The actor keeps E160's
public inputs, terminal labels, action support, stopping rule and deployment.
All labels come from already accepted trajectories; there is no search here.
"""
import argparse
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch

import heart_expected_improvement as I

O, E = I.O, I.E
RECIPE = dict(steps=5000, checkpoints=[0, 250, 500, 1000, 2000, 5000],
              batch_size=128, learning_rate=.0003, weight_decay=.0001,
              gradient_norm=1., validation_draws=8192, seed=2026092264,
              auxiliary_relative_mse_gate=.9)


def registered(root):
    reg = E.read(root / 'registration.json')
    E.require(reg['runner_sha256'] == E.sha(__file__), 'pretraining runner changed')
    for p, digest in reg['hashes'].items():
        E.require(E.sha(p) == digest, 'bound source changed: ' + p)
    plan = E.read(root / 'protocol.json')
    E.require(plan['auxiliary_recipe'] == RECIPE and plan['heart_recipe'] == I.RECIPE,
              'recipe differs from registration')
    E.require(plan['new_training_rollouts'] == 0, 'new collection not permitted')
    return plan


def hp(row, spec, maximum=False):
    column = spec['observations'].index(1 if maximum else 0)
    value = dict(row['observation']).get(column, 0.) * 200.
    rounded = int(round(value))
    E.require(abs(value - rounded) < 1e-3 and rounded >= 0, 'invalid HP encoding')
    return rounded


def targets(before_hp, before_max_hp, after_hp, status, terminal):
    E.require(before_max_hp > 0 and before_hp > 0 and after_hp >= 0, 'invalid combat resources')
    E.require(status in ('death', 'heart_win', 'act3_without_heart'), 'incomplete raw episode')
    death = terminal and status == 'death'
    E.require(not death or after_hp == 0, 'death with remaining HP')
    E.require(death or after_hp > 0, 'surviving transition with no HP')
    return [(after_hp - before_hp) / before_max_hp, float(not death)]


def combat_room(descriptor, action_offset, map_kind, room_offset):
    d = dict(descriptor)
    if d.get(action_offset + map_kind, 0) != 1:
        return None
    rooms = [k for k in (0, 1, 6) if d.get(room_offset + k, 0) == 1]
    return rooms[0] if len(rooms) == 1 else None


def prepare(root):
    plan = registered(root)
    store = O.Store(Path(plan['learning_source']) / 'store')
    graph_root = Path(plan['graph_source'])
    graph_proof = E.read(graph_root / 'completion-verification.json')['hashes']
    x = O.C.D.runtime(plan['runtime'])
    E.require(store.spec == O.C.spec_for(x) and x.A._maxes[:2] == [200., 200.], 'public schema changed')
    output = root / 'data'
    output.mkdir()
    columns = {key: [] for key in ('edges', 'seed', 'act', 'room', 'hp_bin', 'battle_count', 'targets')}
    raw_files = 0
    for number, family in enumerate(store.families):
        path = graph_root / 'families' / f'{family["seed"]}.json.gz'
        E.require(E.sha(path) == graph_proof[str(path)], 'graph changed')
        graph = E.read(path)
        E.require(graph['seed'] == family['seed'] and graph['split'] == 'fit', 'wrong family')
        selected = {}
        for local_edge, edge in enumerate(graph['edges']):
            row = graph['states'][edge['state']]
            room = combat_room(row['descriptors'][edge['action']], x.A.OFF_ACTION, x.A.AK_MAP, x.A.OFF_MROOM)
            if room is not None:
                selected[local_edge] = room
        seen = {}
        for route in graph['routes']:
            E.require(E.sha(route['path']) == route['sha256'], 'raw source changed')
            raw = E.read(route['path'])
            O.G.validate_raw(raw, route, family['seed'], x.identity)
            E.require(raw['terminal_fingerprint'] == route['terminal_fingerprint'], 'terminal changed')
            raw_files += 1
            for at, (prefix_index, local_edge) in enumerate(route['edges']):
                if local_edge not in selected:
                    continue
                edge = graph['edges'][local_edge]
                row = graph['states'][edge['state']]
                step = raw['prefix'][prefix_index]
                E.require(step['kind'] == 'outside' and step['before'] == row['fingerprint']
                          and step['action'] == row['actions'][edge['action']], 'source action differs')
                end = len(raw['prefix']) if edge['done'] else route['edges'][at + 1][0]
                between = raw['prefix'][prefix_index + 1:end]
                E.require(between and all(s['kind'] == 'battle' for s in between), 'map transition is not combat')
                if edge['done']:
                    E.require(at == len(route['edges']) - 1, 'terminal has a successor')
                    after = raw['hp']
                else:
                    next_row = graph['states'][edge['next_state']]
                    E.require(raw['prefix'][end]['before'] == next_row['fingerprint'], 'next state differs')
                    after = hp(next_row, store.spec)
                before, maximum = hp(row, store.spec), hp(row, store.spec, True)
                label = targets(before, maximum, after, raw['status'], edge['done'])
                value = (label, len(between))
                E.require(local_edge not in seen or seen[local_edge] == value, 'same transition has different combat labels')
                seen[local_edge] = value
        E.require(set(seen) == set(selected), 'combat transition lacks raw evidence')
        for local_edge in sorted(selected):
            edge = graph['edges'][local_edge]
            row = graph['states'][edge['state']]
            global_edge = family['edge_begin'] + local_edge
            E.require(store.edge_state[global_edge] == family['begin'] + edge['state'] and
                      store.edge_action[global_edge] == store.menu_ptr[family['begin'] + edge['state']] + edge['action'],
                      'store and graph edge coordinates differ')
            values = dict(edges=global_edge, seed=family['seed'], act=row['act'], room=selected[local_edge],
                          hp_bin=min(3, int(4 * hp(row, store.spec) / hp(row, store.spec, True))),
                          targets=seen[local_edge][0], battle_count=seen[local_edge][1])
            for key in columns:
                columns[key].append(values[key])
        if (number + 1) % 256 == 0:
            print(dict(stage='prepare', families=number+1, combat_transitions=len(columns['edges'])), flush=True)
    for key, values in columns.items():
        np.save(output / (key + '.npy'), np.array(values, dtype=np.float32 if key == 'targets' else np.int64), allow_pickle=False)
    E.write(output / 'report.json', dict(status='complete', families=len(store.families), raw_files=raw_files,
        transitions=len(columns['edges']), deaths=sum(t[1] == 0 for t in columns['targets']),
        battle_span_counts=dict(Counter(columns['battle_count'])), act_counts=dict(Counter(columns['act'])),
        targets=['(next outside or terminal HP - pre-map HP) / pre-map max HP', 'alive after entire transition'],
        limits='Post-combat settlement is included. Consecutive Act3 bosses are one map transition. Deduplicated state/action edges, not independent episodes.',
        new_games=0, MCTS_calls=0, optimizer_updates=0))
    E.write(output / 'completion.json', dict(status='complete', hashes={p.name: E.sha(p) for p in output.iterdir() if p.is_file()}))


class Data:
    def __init__(self, store, path):
        E.proof(path, 'completion.json')
        self.store = store
        for name in ('edges', 'seed', 'act', 'room', 'hp_bin', 'targets', 'battle_count'):
            setattr(self, name, np.load(path / (name + '.npy'), allow_pickle=False))
        self.families = [dict(seed=int(seed), indices=np.flatnonzero(self.seed == seed)) for seed in np.unique(self.seed)]
        self.cells = self.act * 28 + self.room * 4 + self.hp_bin

    def batch(self, ids, allowed):
        E.require(bool(((ids >= 0) & (ids < len(self.edges))).all()), 'invalid auxiliary row')
        E.require(all(int(seed) in allowed for seed in self.seed[ids]), 'held family requested as auxiliary fitting label')
        edges = self.edges[ids]
        features = I.paired_features(self.store, self.store.edge_state[edges], self.store.edge_action[edges])
        return features, torch.from_numpy(self.targets[ids])

    def families_for(self, seeds):
        selected = [f for f in self.families if f['seed'] in set(seeds)]
        E.require({f['seed'] for f in selected} == set(seeds), 'auxiliary family coverage differs')
        return selected

    @staticmethod
    def sample(families, uniforms):
        rows = []
        for a, b in uniforms:
            f = families[min(int(a * len(families)), len(families) - 1)]['indices']
            rows.append(f[min(int(b * len(f)), len(f) - 1)])
        return np.array(rows, dtype=np.int64)

    def baseline(self, families):
        # Mean predictor fitted under the same family-then-transition measure.
        sums = np.zeros((140, 2)); weights = np.zeros(140)
        for family in families:
            ids = family['indices']; weight = 1 / len(ids)
            np.add.at(sums, self.cells[ids], self.targets[ids] * weight)
            np.add.at(weights, self.cells[ids], weight)
        overall = sums.sum(axis=0) / weights.sum()
        return np.where(weights[:, None] > 0, sums / np.maximum(weights[:, None], 1e-12), overall)


def auxiliary_model(width, fold):
    model = I.new_model(width, fold)
    model.tail[-1] = torch.nn.Linear(64, 2)
    torch.nn.init.zeros_(model.tail[-1].weight)
    torch.nn.init.zeros_(model.tail[-1].bias)
    return model


def reset_heart_head(model):
    # A combat-only feature restriction must not silently restrict the later
    # Heart task, whose outcome can depend on the rest of the public map/menu.
    if hasattr(model, 'auxiliary_gradient_hook'):
        model.auxiliary_gradient_hook.remove()
        del model.auxiliary_gradient_hook
    model.tail[-1] = torch.nn.Linear(64, 3)
    torch.nn.init.zeros_(model.tail[-1].weight)
    torch.nn.init.zeros_(model.tail[-1].bias)
    return model


def auxiliary_fit(model, data, families, steps, fold, checkpoint=None):
    optimizer = torch.optim.AdamW(model.parameters(), lr=RECIPE['learning_rate'], weight_decay=RECIPE['weight_decay'])
    rng = np.random.default_rng(RECIPE['seed'] + fold)
    allowed = {f['seed'] for f in families}
    if checkpoint:
        checkpoint(0, model)
    for step in range(1, steps + 1):
        ids = data.sample(families, rng.random((RECIPE['batch_size'], 2)))
        features, labels = data.batch(ids, allowed)
        loss = (model(features) - labels).square().mean()
        O.gradient_step(loss, optimizer, model, RECIPE['gradient_norm'])
        if checkpoint and step in RECIPE['checkpoints']:
            checkpoint(step, model)


def mse(model, data, ids, allowed):
    total = np.zeros(2)
    with torch.inference_mode():
        for start in range(0, len(ids), 128):
            features, labels = data.batch(ids[start:start + 128], allowed)
            total += (model(features) - labels).square().sum(dim=0).numpy()
    return (total / len(ids)).tolist()


def train(root, *, model_factory=auxiliary_model, registration=registered):
    plan = registration(root)
    review = E.read(root / 'data-review.json')
    E.require(review['status'] == 'complete_reviewed' and
              review['data_completion_sha256'] == E.sha(root / 'data/completion.json'), 'combat labels not reviewed')
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = Data(store, root / 'data')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    examples = I.Examples(store, exact['observed_best'])
    output = root / 'learning'; output.mkdir()
    width = store.spec['width'] + store.spec['descriptor_dim']
    auxiliary = []
    for fold in range(3):
        fit = [f for f in examples.families if O.T.fold(f['seed']) != fold]
        inner, valid = O.inner_partition(fit)
        a_inner, a_valid, a_fit, a_held = [data.families_for([f['seed'] for f in group]) for group in
            (inner, valid, fit, [f for f in examples.families if O.T.fold(f['seed']) == fold])]
        directory = output / f'fold-{fold}'; directory.mkdir()
        rng = np.random.default_rng(RECIPE['seed'] + 2000 + fold)
        ids = data.sample(a_valid, rng.random((RECIPE['validation_draws'], 2)))
        held_ids = data.sample(a_held, rng.random((RECIPE['validation_draws'], 2)))
        E.write(directory / 'auxiliary-roles.json', dict(inner_train=[f['seed'] for f in inner], inner_validation=[f['seed'] for f in valid],
            fit=[f['seed'] for f in fit], held=[f['seed'] for f in a_held], validation_ids=ids.tolist(), held_ids=held_ids.tolist()))
        curve = []
        model = model_factory(width, fold)
        def checkpoint(step, current):
            losses = mse(current, data, ids, {f['seed'] for f in a_valid})
            curve.append(dict(step=step, mse=losses, loss=float(np.mean(losses))))
            torch.save(current.state_dict(), directory / f'aux-inner-{step}.pt')
        auxiliary_fit(model, data, a_inner, RECIPE['steps'], fold, checkpoint)
        selected = min(curve, key=lambda r: (r['loss'], r['step']))['step']
        model = model_factory(width, fold)
        auxiliary_fit(model, data, a_fit, selected, fold)
        torch.save(model.state_dict(), directory / 'auxiliary.pt')
        baseline = data.baseline(a_fit)[data.cells[held_ids]]
        neural = mse(model, data, held_ids, {f['seed'] for f in a_held})
        old = ((baseline - data.targets[held_ids]) ** 2).mean(axis=0).tolist()
        row = dict(fold=fold, selected_steps=selected, held_mse=neural, held_baseline_mse=old,
                   inner_baseline_mse=((data.baseline(a_inner)[data.cells[ids]] - data.targets[ids]) ** 2).mean(axis=0).tolist())
        auxiliary.append(row)
        E.write(directory / 'auxiliary-stopping.json', curve)
        E.write(directory / 'auxiliary-report.json', row)
        print(dict(stage='auxiliary', **row), flush=True)
    neural = float(np.mean([r['held_mse'] for r in auxiliary]))
    baseline = float(np.mean([r['held_baseline_mse'] for r in auxiliary]))
    passed = neural <= RECIPE['auxiliary_relative_mse_gate'] * baseline and all(np.mean(r['held_mse']) < np.mean(r['held_baseline_mse']) for r in auxiliary)
    E.write(output / 'auxiliary-screen.json', dict(folds=auxiliary, mse=neural, baseline_mse=baseline, passed=passed))
    models, screens = [], []
    if passed:
        base = torch.load(Path(plan['runtime']) / 'model.pt', weights_only=True, map_location='cpu')
        for fold, aux in enumerate(auxiliary):
            families = [f for f in examples.families if O.T.fold(f['seed']) != fold]
            inner, valid = O.inner_partition(families)
            directory = output / f'fold-{fold}'
            rng = np.random.default_rng(I.RECIPE['seed'] + 2000 + fold)
            ids = examples.sample(valid, rng.random((I.RECIPE['validation_draws'], 3)))
            E.write(directory / 'actor-validation.json', dict(indices=ids.tolist(), inner_train=[f['seed'] for f in inner], inner_validation=[f['seed'] for f in valid]))
            model = model_factory(width, fold)
            model.load_state_dict(torch.load(directory / f'aux-inner-{aux["selected_steps"]}.pt', weights_only=True))
            reset_heart_head(model)
            curve = []
            def checkpoint(step, current):
                curve.append(dict(step=step, loss=I.validation_loss(current, examples, ids, valid)))
                torch.save(current.state_dict(), directory / f'inner-{step}.pt')
            I.fit(model, examples, inner, I.RECIPE['steps'], fold, checkpoint)
            selected = min(curve, key=lambda r: (r['loss'], r['step']))['step']
            model = model_factory(width, fold)
            model.load_state_dict(torch.load(directory / 'auxiliary.pt', weights_only=True))
            reset_heart_head(model)
            I.fit(model, examples, families, selected, fold)
            indices = np.concatenate([f['indices'] for f in families])
            support = sorted({store.identities[int(i)] for i in store.candidate_identity[store.edge_action[examples.edges[indices]]].tolist()})
            path = directory / 'candidate.pt'
            torch.save(dict(model_type=I.MODEL_TYPE, actor_state=model.state_dict(), base_checkpoint=base,
                feature_spec=store.spec, paired_width=width, support=support, arm='combat_pretraining',
                provenance=dict(fold=fold, fit_families=[f['seed'] for f in families], selected_actor_steps=selected,
                    selected_auxiliary_steps=aux['selected_steps'], recipe=I.RECIPE, auxiliary_recipe=RECIPE)), path)
            E.write(directory / 'stopping.json', curve)
            screen = I.branch_screen(model, examples, fold, support)
            E.write(directory / 'branch-screen.json', screen)
            screens.append(screen)
            models.append(dict(fold=fold, path=str(path), sha256=E.sha(path), selected_actor_steps=selected))
            print(dict(stage='heart', fold=fold, selected_steps=selected, screen=screen), flush=True)
    aggregate = {role: Counter() for role in ('fit', 'held')}
    for screen in screens:
        for role in aggregate:
            aggregate[role].update(screen[role])
    fitting, held = aggregate['fit'], aggregate['held']
    eligible = bool(passed and fitting['known_gains'] >= .5 * fitting['improvement_available']
                    and fitting['known_gains'] > fitting['known_losses'] and held['known_gains'] > held['known_losses'])
    E.write(output / 'report.json', dict(status='complete', models=models, auxiliary_passed=passed,
        branch_screen={role: dict(counts) for role, counts in aggregate.items()}, eligible_for_natural_evaluation=eligible,
        auxiliary_optimizer_steps=3 * RECIPE['steps'] + sum(r['selected_steps'] for r in auxiliary),
        heart_optimizer_steps=(3 * I.RECIPE['steps'] if passed else 0) + sum(m['selected_actor_steps'] for m in models),
        new_training_rollouts=0, production_adoption=False))
    E.write(output / 'completion.json', dict(status='complete', hashes={str(p.relative_to(output)): E.sha(p) for p in output.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'prepare': prepare, 'train': train, 'check': registered}[args.command](args.study.resolve())
