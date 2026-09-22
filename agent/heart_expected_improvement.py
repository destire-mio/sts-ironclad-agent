"""Predict gain/tie/loss versus the parent from existing recorded alternatives.

The decision score is P(gain)-P(loss), not the most likely category. Paired
labels use exact recorded-graph continuations; hidden outcomes are labels only.
No simulator or sampling code is used by the trainer.
"""
import argparse
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as NN

import heart_offline_control as O

E = O.E
MODEL_TYPE = 'expected_heart_improvement'
RECIPE = dict(steps=2000, batch_size=128, learning_rate=.0003, weight_decay=.0001,
              gradient_norm=1., validation_draws=8192, seed=2026092260)


class ImprovementModel(O.Actor):
    def __init__(self, width):
        super().__init__(width)
        self.tail[-1] = torch.nn.Linear(64, 3)

    def forward(self, features):
        # The parent class squeezes the scalar output; preserve three logits.
        hidden = (torch.sparse.mm(features, self.input.weight.T) + self.input.bias
                  if features.is_sparse else self.input(features))
        return self.tail(hidden)


def new_model(width, fold):
    torch.manual_seed(RECIPE['seed'] + fold)
    model = ImprovementModel(width)
    torch.nn.init.zeros_(model.tail[-1].weight)
    torch.nn.init.zeros_(model.tail[-1].bias)
    return model


def expected_delta(logits):
    probability = logits.softmax(dim=-1)
    return probability[..., 2] - probability[..., 0]


def paired_features(store, states, actions):
    current = store.action_features(states, actions)
    parent = store.descriptors.take(store.parent[states])
    indices = parent.indices().clone()
    indices[1] += store.spec['width']
    return torch.sparse_coo_tensor(
        torch.cat([current.indices(), indices], dim=1),
        torch.cat([current.values(), parent.values()]),
        (len(states), store.spec['width'] + store.spec['descriptor_dim']),
        check_invariants=True).coalesce()


class Examples:
    def __init__(self, store, observed_best):
        self.store = store
        q = np.where(store.done, store.reward, observed_best[store.next_state])
        parental = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
        E.require(len(parental) == store.states, 'every state must have one parent action')
        parent_q = np.empty(store.states, dtype=np.float32)
        parent_q[store.edge_state[parental]] = q[parental]
        self.edges = np.flatnonzero(store.edge_action != store.parent[store.edge_state])
        difference = q[self.edges] - parent_q[store.edge_state[self.edges]]
        self.q, self.parent_q = q, parent_q
        E.require(bool(np.isin(difference, [-1, 0, 1]).all()), 'nonbinary paired return')
        self.labels = (difference + 1).astype(np.int64)
        self.seeds = np.empty(len(self.edges), dtype=np.int64)
        self.families = []
        for family in store.families:
            a, b = np.searchsorted(self.edges, [family['edge_begin'], family['edge_end']])
            if a == b:
                continue
            indices = np.arange(a, b)
            ordered = indices[np.argsort(store.edge_state[self.edges[indices]], kind='stable')]
            states = store.edge_state[self.edges[ordered]]
            groups = np.split(ordered, np.flatnonzero(np.diff(states)) + 1)
            self.seeds[indices] = family['seed']
            self.families.append(dict(seed=family['seed'], groups=groups, indices=indices))

    def sample(self, families, uniforms):
        def pick(items, u):
            return items[min(int(len(items) * u), len(items) - 1)]
        return np.array([pick(pick(pick(families, u[0])['groups'], u[1]), u[2]) for u in uniforms], dtype=np.int64)

    def batch(self, indices, permitted_seeds):
        # Roles are checked by actual global row ownership, not caller names.
        E.require(bool(((indices >= 0) & (indices < len(self.edges))).all()), 'invalid example')
        E.require(all(int(seed) in permitted_seeds for seed in self.seeds[indices]), 'held family requested as fitting label')
        edges = self.edges[indices]
        return paired_features(self.store, self.store.edge_state[edges], self.store.edge_action[edges]), torch.from_numpy(self.labels[indices])


def fit(model, examples, families, steps, fold, checkpoint=None):
    optimizer = torch.optim.AdamW(model.parameters(), lr=RECIPE['learning_rate'], weight_decay=RECIPE['weight_decay'])
    rng = np.random.default_rng(RECIPE['seed'] + 1000 + fold)
    allowed = {f['seed'] for f in families}
    if checkpoint:
        checkpoint(0, model)
    for step in range(1, steps + 1):
        ids = examples.sample(families, rng.random((RECIPE['batch_size'], 3)))
        features, labels = examples.batch(ids, allowed)
        loss = NN.cross_entropy(model(features), labels)
        O.gradient_step(loss, optimizer, model, RECIPE['gradient_norm'])
        if checkpoint and step in O.CHECKPOINTS:
            checkpoint(step, model)


def validation_loss(model, examples, indices, families):
    total = 0.
    with torch.inference_mode():
        for at in range(0, len(indices), 128):
            features, labels = examples.batch(indices[at:at + 128], {f['seed'] for f in families})
            total += float(NN.cross_entropy(model(features), labels, reduction='sum'))
    return total / len(indices)


def registered(root):
    registration = E.read(root / 'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'expected-improvement runner changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound source changed: ' + path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['recipe'] == RECIPE, 'recipe changed')
    E.require(E.read(Path(plan['path_diagnosis']) / 'result-review.json')['status'] == 'complete_reviewed', 'E159 diagnosis not admitted')
    E.require(E.read(Path(plan['preceding_study']) / 'result-review.json')['status'] == 'complete_reviewed', 'E158 not admitted')
    return plan


def branch_screen(model, examples, fold, support):
    store = examples.store
    states = np.unique(store.edge_state[examples.edges])
    allowed = O.supported_candidates(store, set(support))
    owners = np.empty(store.states, dtype=np.int8)
    for family in store.families:
        owners[family['begin']:family['end']] = O.T.fold(family['seed'])
    report = {role: Counter() for role in ('fit', 'held')}
    for at in range(0, len(states), 64):
        batch = states[at:at+64]
        sizes = store.menu_ptr[batch + 1] - store.menu_ptr[batch]
        ptr = np.r_[0, np.cumsum(sizes)]
        actions = np.concatenate([np.arange(store.menu_ptr[s], store.menu_ptr[s+1]) for s in batch])
        features = paired_features(store, np.repeat(batch, sizes), actions)
        with torch.inference_mode():
            scores = expected_delta(model(features.to_dense())).numpy()
        for i, state in enumerate(batch):
            a, b = ptr[i:i+2]
            parent = int(store.parent[state] - store.menu_ptr[state])
            mask = allowed[actions[a:b]].copy()
            mask[parent] = True
            scores[a+parent] = 0.
            choice = max(np.flatnonzero(mask), key=lambda k: (float(scores[a+k]), k == parent, -k))
            u, v = store.state_edge_ptr[state:state+2]
            edges = store.state_edge_ids[u:v]
            row = report['held' if owners[state] == fold else 'fit']
            row['states'] += 1
            can_improve = examples.q[edges].max() > examples.parent_q[state]
            row['improvement_available'] += int(can_improve)
            row['parent_choices'] += int(choice == parent)
            found = edges[store.edge_action[edges] == store.menu_ptr[state] + choice]
            if len(found) == 0:
                row['unrecorded_choices'] += 1
            else:
                delta = examples.q[found[0]] - examples.parent_q[state]
                row['known_gains'] += int(delta > 0)
                row['known_losses'] += int(delta < 0)
                row['known_ties'] += int(delta == 0)
    return {role: dict(row) for role, row in report.items()}


def train(root):
    plan = registered(root)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    examples = Examples(store, exact['observed_best'])
    output = root / 'learning'
    output.mkdir()
    base = torch.load(Path(plan['runtime']) / 'model.pt', weights_only=True, map_location='cpu')
    models, screens = [], []
    for fold in range(3):
        families = [f for f in examples.families if O.T.fold(f['seed']) != fold]
        inner, valid = O.inner_partition(families)
        rng = np.random.default_rng(RECIPE['seed'] + 2000 + fold)
        ids = examples.sample(valid, rng.random((RECIPE['validation_draws'], 3)))
        directory = output / f'fold-{fold}'
        directory.mkdir()
        E.write(directory / 'actor-validation.json', dict(indices=ids.tolist(), inner_train=[f['seed'] for f in inner], inner_validation=[f['seed'] for f in valid]))
        width = store.spec['width'] + store.spec['descriptor_dim']
        model = new_model(width, fold)
        curve = []
        started = time.monotonic()

        def checkpoint(step, current):
            curve.append(dict(step=step, loss=validation_loss(current, examples, ids, valid)))
            torch.save(current.state_dict(), directory / f'inner-{step}.pt')

        fit(model, examples, inner, RECIPE['steps'], fold, checkpoint)
        selected = min(curve, key=lambda r: (r['loss'], r['step']))['step']
        model = new_model(width, fold)
        fit(model, examples, families, selected, fold)
        fit_ids = np.concatenate([f['indices'] for f in families])
        support = sorted({store.identities[int(i)] for i in store.candidate_identity[store.edge_action[examples.edges[fit_ids]]].tolist()})
        path = directory / 'candidate.pt'
        torch.save(dict(model_type=MODEL_TYPE, actor_state=model.state_dict(), base_checkpoint=base,
            feature_spec=store.spec, paired_width=width, support=support, arm='expected_improvement',
            provenance=dict(fold=fold, fit_families=[f['seed'] for f in families], selected_actor_steps=selected,
                exact_values_sha256=E.sha(Path(plan['diagnosis']) / 'exact-observed-values.npz'), recipe=RECIPE)), path)
        E.write(directory / 'stopping.json', curve)
        screen = branch_screen(model, examples, fold, support)
        E.write(directory / 'branch-screen.json', screen)
        screens.append(screen)
        record = dict(fold=fold, path=str(path), sha256=E.sha(path), selected_actor_steps=selected, seconds=time.monotonic() - started)
        models.append(record)
        print(dict(stage='actor', **record), flush=True)
    aggregate = {role: Counter() for role in ('fit', 'held')}
    for screen in screens:
        for role in aggregate:
            aggregate[role].update(screen[role])
    fitting, held = aggregate['fit'], aggregate['held']
    eligible = (fitting['known_gains'] >= .5 * fitting['improvement_available']
                and fitting['known_gains'] > fitting['known_losses']
                and held['known_gains'] > held['known_losses'])
    E.write(output / 'report.json', dict(status='complete', models=models,
        branch_screen={role: dict(counts) for role, counts in aggregate.items()}, eligible_for_natural_evaluation=eligible,
        actor_optimizer_steps=3 * RECIPE['steps'] + sum(m['selected_actor_steps'] for m in models),
        critic_optimizer_steps=0, new_training_rollouts=0, production_adoption=False))
    E.write(output / 'completion.json', dict(status='complete', hashes={str(p.relative_to(output)): E.sha(p) for p in output.rglob('*') if p.is_file()}))


def evaluate(root):
    import heart_offline_control_evaluation as N
    plan = registered(root)
    E.proof(root / 'learning', 'completion.json')
    review = E.read(root / 'training-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['eligible_for_natural_evaluation'], 'learning screen/review failed')
    E.require(review['learning_completion_sha256'] == E.sha(root / 'learning/completion.json'), 'review belongs to different learning')
    source = Path(plan['learning_source'])
    graph = Path(E.read(source / 'protocol.json')['source'])
    continuous = Path(E.read(graph / 'protocol.json')['continuous_source'])
    seeds = O.T.pilot_seeds(E.read(continuous / 'fit-roles.json'))
    refs = E.indexed(E.read(continuous / 'fit-references.json'), 'seed', 'reference')
    x = O.C.D.runtime(plan['runtime'])
    config = dict(x.config, workers=8)
    E.require(config['simulations'] == 8000 and config['boss_multiplier'] == 3 and config['ascension'] == 20, 'combat budget changed')
    out = root / 'evaluation'
    out.mkdir()
    jobs = []
    for seed in seeds:
        cp = root / 'learning' / f'fold-{O.T.fold(seed)}' / 'candidate.pt'
        jobs.append(dict(mode='prefix', arm='expected_improvement', seed=seed, runtime=plan['runtime'], reference=refs[seed], checkpoint=str(cp), checkpoint_sha256=E.sha(cp), output=str(out / 'expected_improvement' / f'{seed}.json.gz')))
    deadline = time.monotonic() + plan['evaluation_timeout_seconds']
    rows = x.H.run_jobs(out, jobs, config, 'E160_full_runs', deadline, worker_fn=N.evaluate_worker)
    E.require(len(rows) == len(jobs) and [r['seed'] for r in rows] == seeds, 'assigned evaluation differs')
    faults = [dict(seed=r.get('seed'), status=r['status'], error=r.get('error')) for r in rows if r['status'] not in ('death', 'heart_win', 'act3_without_heart') or r.get('error')]
    E.write(out / 'faults.json', faults)
    E.require(not faults, 'evaluation fault; retain all assigned games')
    repeats = [dict(j, repeat=dict(path=j['output'], sha256=E.sha(j['output'])), output=str(out / 'repeated' / f'{j["seed"]}.json.gz')) for j, r in zip(jobs, rows) if r['status'] == 'heart_win']
    repeated = x.H.run_jobs(out, repeats, config, 'E160_winner_replans', deadline, worker_fn=N.evaluate_worker) if repeats else []
    E.require(len(repeated) == len(repeats) and all(r['status'] == 'heart_win' and r.get('fresh_replan_matched') for r in repeated), 'fresh winner replay failed')
    chosen = [int(r['status'] == 'heart_win') for r in rows]
    previous = Path(plan['preceding_study'])
    E.proof(previous / 'evaluation', 'completion-verification.json')
    comparisons = dict(parent=x.B.paired_counts([int(refs[s]['status'] == 'heart_win') for s in seeds], chosen), parent_preserving=x.B.paired_counts([int(E.read(previous / 'evaluation/parent_preserving' / f'{s}.json.gz')['status'] == 'heart_win') for s in seeds], chosen))
    counts = comparisons['parent']
    E.write(out / 'report.json', dict(status='complete', families=128, comparisons=comparisons,
        gate_passed=counts['net_gain'] >= 8 and counts['exact_p'] < .025,
        natural_policy_evaluation_games=len(rows), winner_replans=len(repeats), zero_faults=True,
        new_training_rollouts=0, reserved_development_games=0, unseen_acceptance_games=0, production_adoption=False))
    paths = [Path(j['output']) for j in jobs + repeats] + [out / 'faults.json', out / 'report.json']
    E.write(out / 'completion-verification.json', dict(status='complete', zero_faults=True, hashes={str(p.relative_to(out)): E.sha(p) for p in paths}))


class ImprovementPolicy(torch.nn.Module):
    def __init__(self, checkpoint, x):
        super().__init__()
        E.require(checkpoint['model_type'] == MODEL_TYPE, 'wrong improvement model')
        E.require(checkpoint['feature_spec'] == O.C.spec_for(x), 'public schema changed')
        self.x, self.spec = x, checkpoint['feature_spec']
        self.support = set(checkpoint['support'])
        self.base = x.H.load_scorer(checkpoint['base_checkpoint']).eval()
        E.require(checkpoint['paired_width'] == self.spec['width'] + self.spec['descriptor_dim'], 'paired width changed')
        self.actor = ImprovementModel(checkpoint['paired_width'])
        self.actor.load_state_dict(checkpoint['actor_state'])
        self.requires_grad_(False)
        self.eval()

    def choose(self, gc, observation, actions, descriptors):
        parent = self.base.choose(gc, observation, actions, descriptors)
        if len(actions) == 1:
            return parent
        row = dict(observation=self.x.R.sparse([observation[i] for i in self.spec['observations']]), descriptors=[self.x.R.sparse(d) for d in descriptors])
        features = torch.zeros((len(actions), self.spec['width'] + self.spec['descriptor_dim']))
        for i in range(len(actions)):
            for j, value in O.C.sparse_features(row, i, self.spec):
                features[i, j] = value
        features[:, self.spec['width']:] = torch.tensor(descriptors[parent], dtype=torch.float32)
        with torch.inference_mode():
            scores = expected_delta(self.actor(features)).tolist()
        scores[parent] = 0.
        return O.V.select(row, scores, parent, self.support, self.spec)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('train', 'evaluate', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'train': train, 'evaluate': evaluate, 'check': registered}[args.command](args.study.resolve())
