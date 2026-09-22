"""A shared utility difference defines the sign of action improvement.

Both action encodings retain the same actual parent recommendation. Swapping
the compared actions reverses gain/loss and preserves tie probability. Reuse
E165's admitted combat encoders; do not train another auxiliary model.
"""
import argparse
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as NN

import heart_combat_pretraining as P

I, O, E = P.I, P.O, P.E
MODEL_TYPE = 'structured_heart_improvement'


def pair_logits(action, reference):
    difference = action[..., 0] - reference[..., 0]
    tie = .5 * (action[..., 1] + reference[..., 1])
    return torch.stack((-difference, tie, difference), dim=-1)


def menu_scores(outputs, parent):
    return I.expected_delta(pair_logits(outputs, outputs[parent]))


def warm_model(source, width, fold, inner):
    directory = source / 'learning' / f'fold-{fold}'
    step = E.read(directory / 'auxiliary-report.json')['selected_steps']
    path = directory / (f'aux-inner-{step}.pt' if inner else 'auxiliary.pt')
    model = P.auxiliary_model(width, fold)
    model.load_state_dict(torch.load(path, weights_only=True, map_location='cpu'))
    # Utility and tie heads have no inherited HP/survival semantics.
    torch.nn.init.zeros_(model.tail[-1].weight)
    torch.nn.init.zeros_(model.tail[-1].bias)
    return model


def batch(examples, ids, allowed):
    chosen, labels = examples.batch(ids, allowed)
    store = examples.store
    states = store.edge_state[examples.edges[ids]]
    # The third logical input, actual parent's descriptor, remains fixed for
    # both alternatives. This is not a swap of the teacher recommendation.
    reference = I.paired_features(store, states, store.parent[states])
    return chosen, reference, labels


def fit(model, examples, families, steps, fold, checkpoint=None):
    recipe = I.RECIPE
    optimizer = torch.optim.AdamW(model.parameters(), lr=recipe['learning_rate'], weight_decay=recipe['weight_decay'])
    rng = np.random.default_rng(recipe['seed'] + 1000 + fold)
    allowed = {f['seed'] for f in families}
    if checkpoint:
        checkpoint(0, model)
    for step in range(1, steps + 1):
        ids = examples.sample(families, rng.random((recipe['batch_size'], 3)))
        action, reference, labels = batch(examples, ids, allowed)
        logits = pair_logits(model(action), model(reference))
        O.gradient_step(NN.cross_entropy(logits, labels), optimizer, model, recipe['gradient_norm'])
        if checkpoint and step in O.CHECKPOINTS:
            checkpoint(step, model)


def validation_loss(model, examples, ids, families):
    total = 0.
    with torch.inference_mode():
        for start in range(0, len(ids), 128):
            a, b, y = batch(examples, ids[start:start+128], {f['seed'] for f in families})
            total += float(NN.cross_entropy(pair_logits(model(a), model(b)), y, reduction='sum'))
    return total / len(ids)


def branch_screen(model, examples, fold, support):
    store = examples.store
    states = np.unique(store.edge_state[examples.edges])
    permitted = O.supported_candidates(store, set(support))
    owners = np.empty(store.states, dtype=np.int8)
    for family in store.families:
        owners[family['begin']:family['end']] = O.T.fold(family['seed'])
    result = {role: Counter() for role in ('fit', 'held')}
    for start in range(0, len(states), 64):
        selected = states[start:start+64]
        sizes = store.menu_ptr[selected+1] - store.menu_ptr[selected]
        ptr = np.r_[0, np.cumsum(sizes)]
        actions = np.concatenate([np.arange(store.menu_ptr[s], store.menu_ptr[s+1]) for s in selected])
        with torch.inference_mode():
            outputs = model(I.paired_features(store, np.repeat(selected, sizes), actions).to_dense())
        for at, state in enumerate(selected):
            a, b = ptr[at:at+2]
            parent = int(store.parent[state] - store.menu_ptr[state])
            scores = menu_scores(outputs[a:b], parent).numpy()
            E.require(scores[parent] == 0., 'self comparison was not zero')
            allowed = permitted[actions[a:b]].copy(); allowed[parent] = True
            choice = max(np.flatnonzero(allowed), key=lambda k: (float(scores[k]), k == parent, -k))
            u, v = store.state_edge_ptr[state:state+2]
            edges = store.state_edge_ids[u:v]
            row = result['held' if owners[state] == fold else 'fit']
            row['states'] += 1
            row['improvement_available'] += int(examples.q[edges].max() > examples.parent_q[state])
            row['parent_choices'] += int(choice == parent)
            found = edges[store.edge_action[edges] == store.menu_ptr[state] + choice]
            if len(found):
                delta = examples.q[found[0]] - examples.parent_q[state]
                row['known_gains'] += int(delta > 0)
                row['known_losses'] += int(delta < 0)
                row['known_ties'] += int(delta == 0)
            else:
                row['unrecorded_choices'] += 1
    return {k: dict(v) for k, v in result.items()}


def registered(root):
    reg = E.read(root / 'registration.json')
    E.require(reg['runner_sha256'] == E.sha(__file__), 'structured comparison runner changed')
    for path, digest in reg['hashes'].items():
        E.require(E.sha(path) == digest, 'registered source changed: ' + path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['heart_recipe'] == I.RECIPE and plan['new_training_rollouts'] == 0, 'budget/recipe changed')
    source = Path(plan['encoder_source'])
    review = E.read(source / 'auxiliary-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['passed'], 'combat representation not admitted')
    E.require(review['learning_completion_sha256'] == E.sha(source / 'learning/completion.json'), 'wrong encoder completion')
    return plan


def train(root):
    plan = registered(root)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    examples = I.Examples(store, exact['observed_best'])
    source = Path(plan['encoder_source'])
    E.proof(source / 'learning', 'completion.json')
    output = root / 'learning'; output.mkdir()
    width = store.spec['width'] + store.spec['descriptor_dim']
    base = torch.load(Path(plan['runtime']) / 'model.pt', weights_only=True, map_location='cpu')
    models, screens = [], []
    for fold in range(3):
        families = [f for f in examples.families if O.T.fold(f['seed']) != fold]
        inner, valid = O.inner_partition(families)
        roles = E.read(source / 'learning' / f'fold-{fold}/auxiliary-roles.json')
        E.require(roles['inner_train'] == [f['seed'] for f in inner] and roles['inner_validation'] == [f['seed'] for f in valid]
                  and roles['fit'] == [f['seed'] for f in families], 'warm encoder family roles differ')
        directory = output / f'fold-{fold}'; directory.mkdir()
        rng = np.random.default_rng(I.RECIPE['seed'] + 2000 + fold)
        ids = examples.sample(valid, rng.random((I.RECIPE['validation_draws'], 3)))
        E.write(directory / 'actor-validation.json', dict(indices=ids.tolist(), inner_train=[f['seed'] for f in inner], inner_validation=[f['seed'] for f in valid]))
        model = warm_model(source, width, fold, True)
        curve = []
        def checkpoint(step, current):
            curve.append(dict(step=step, loss=validation_loss(current, examples, ids, valid)))
            torch.save(current.state_dict(), directory / f'inner-{step}.pt')
        fit(model, examples, inner, I.RECIPE['steps'], fold, checkpoint)
        selected = min(curve, key=lambda r: (r['loss'], r['step']))['step']
        model = warm_model(source, width, fold, False)
        fit(model, examples, families, selected, fold)
        indices = np.concatenate([f['indices'] for f in families])
        support = sorted({store.identities[int(i)] for i in store.candidate_identity[store.edge_action[examples.edges[indices]]].tolist()})
        path = directory / 'candidate.pt'
        torch.save(dict(model_type=MODEL_TYPE, actor_state=model.state_dict(), base_checkpoint=base,
            feature_spec=store.spec, paired_width=width, support=support, arm='structured_comparison',
            provenance=dict(fold=fold, fit_families=[f['seed'] for f in families], selected_actor_steps=selected,
                encoder_sha256=E.sha(source / 'learning' / f'fold-{fold}/auxiliary.pt'), recipe=I.RECIPE)), path)
        E.write(directory / 'stopping.json', curve)
        screen = branch_screen(model, examples, fold, support)
        E.write(directory / 'branch-screen.json', screen); screens.append(screen)
        models.append(dict(fold=fold, path=str(path), sha256=E.sha(path), selected_actor_steps=selected))
        print(dict(stage='heart', fold=fold, selected_steps=selected, screen=screen), flush=True)
    aggregate = {role: Counter() for role in ('fit', 'held')}
    for screen in screens:
        for role in aggregate:
            aggregate[role].update(screen[role])
    fitting, held = aggregate['fit'], aggregate['held']
    eligible = bool(fitting['known_gains'] >= .5 * fitting['improvement_available'] and
                    fitting['known_gains'] > fitting['known_losses'] and held['known_gains'] > held['known_losses'])
    E.write(output / 'report.json', dict(status='complete', models=models,
        branch_screen={k: dict(v) for k, v in aggregate.items()}, eligible_for_natural_evaluation=eligible,
        actor_optimizer_steps=3 * I.RECIPE['steps'] + sum(m['selected_actor_steps'] for m in models),
        auxiliary_optimizer_steps=0, new_training_rollouts=0, production_adoption=False))
    E.write(output / 'completion.json', dict(status='complete', hashes={str(p.relative_to(output)): E.sha(p) for p in output.rglob('*') if p.is_file()}))


def evaluate(root):
    import heart_offline_control_evaluation as N
    plan = registered(root)
    E.proof(root / 'learning', 'completion.json')
    review = E.read(root / 'training-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['eligible_for_natural_evaluation'], 'learning screen/review failed')
    E.require(review['learning_completion_sha256'] == E.sha(root / 'learning/completion.json'), 'review belongs to different learning')
    graph = Path(E.read(Path(plan['learning_source']) / 'protocol.json')['source'])
    continuous = Path(E.read(graph / 'protocol.json')['continuous_source'])
    seeds = O.T.pilot_seeds(E.read(continuous / 'fit-roles.json'))
    refs = E.indexed(E.read(continuous / 'fit-references.json'), 'seed', 'reference')
    x = O.C.D.runtime(plan['runtime'])
    config = dict(x.config, workers=8)
    E.require(config['simulations'] == 8000 and config['boss_multiplier'] == 3 and config['ascension'] == 20, 'combat budget changed')
    out = root / 'evaluation'; out.mkdir()
    jobs = []
    for seed in seeds:
        checkpoint = root / 'learning' / f'fold-{O.T.fold(seed)}' / 'candidate.pt'
        jobs.append(dict(mode='prefix', arm='structured_comparison', seed=seed, runtime=plan['runtime'], reference=refs[seed],
            checkpoint=str(checkpoint), checkpoint_sha256=E.sha(checkpoint), output=str(out / 'structured_comparison' / f'{seed}.json.gz')))
    deadline = time.monotonic() + plan['evaluation_timeout_seconds']
    rows = x.H.run_jobs(out, jobs, config, 'E166_full_runs', deadline, worker_fn=N.evaluate_worker)
    E.require(len(rows) == len(jobs) and [r['seed'] for r in rows] == seeds, 'assigned evaluation differs')
    faults = [dict(seed=r.get('seed'), status=r['status'], error=r.get('error')) for r in rows if r['status'] not in ('death', 'heart_win', 'act3_without_heart') or r.get('error')]
    E.write(out / 'faults.json', faults)
    E.require(not faults, 'evaluation fault; retain all assigned games')
    repeats = [dict(j, repeat=dict(path=j['output'], sha256=E.sha(j['output'])), output=str(out / 'repeated' / f'{j["seed"]}.json.gz')) for j, r in zip(jobs, rows) if r['status'] == 'heart_win']
    repeated = x.H.run_jobs(out, repeats, config, 'E166_winner_replans', deadline, worker_fn=N.evaluate_worker) if repeats else []
    E.require(len(repeated) == len(repeats) and all(r['status'] == 'heart_win' and r.get('fresh_replan_matched') for r in repeated), 'fresh winner replay failed')
    counts = x.B.paired_counts([int(refs[s]['status'] == 'heart_win') for s in seeds], [int(r['status'] == 'heart_win') for r in rows])
    E.write(out / 'report.json', dict(status='complete', families=128, parent_comparison=counts,
        gate_passed=counts['net_gain'] >= 8 and counts['exact_p'] < .025,
        natural_policy_evaluation_games=len(rows), winner_replans=len(repeats), zero_faults=True,
        new_training_rollouts=0, reserved_development_games=0, unseen_acceptance_games=0, production_adoption=False))
    paths = [Path(j['output']) for j in jobs + repeats] + [out / 'faults.json', out / 'report.json']
    E.write(out / 'completion-verification.json', dict(status='complete', zero_faults=True, hashes={str(p.relative_to(out)): E.sha(p) for p in paths}))


class StructuredPolicy(torch.nn.Module):
    def __init__(self, checkpoint, x):
        super().__init__()
        E.require(checkpoint['model_type'] == MODEL_TYPE, 'wrong structured model')
        E.require(checkpoint['feature_spec'] == O.C.spec_for(x), 'public schema changed')
        self.x, self.spec = x, checkpoint['feature_spec']
        self.support = set(checkpoint['support'])
        self.base = x.H.load_scorer(checkpoint['base_checkpoint']).eval()
        E.require(checkpoint['paired_width'] == self.spec['width'] + self.spec['descriptor_dim'], 'paired width changed')
        self.actor = P.auxiliary_model(checkpoint['paired_width'], 0)
        self.actor.load_state_dict(checkpoint['actor_state'])
        self.requires_grad_(False); self.eval()

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
            scores = menu_scores(self.actor(features), parent).tolist()
        return O.V.select(row, scores, parent, self.support, self.spec)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('train', 'evaluate', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'train': train, 'evaluate': evaluate, 'check': registered}[args.command](args.study.resolve())
