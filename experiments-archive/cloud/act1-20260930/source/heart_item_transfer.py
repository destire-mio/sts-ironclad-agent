"""Reuse trained inventory embeddings when representing an offered item.

This is feature sharing, not a simulated afterstate. A candidate contributes
an item token through the same weights as owned items; random acquisition
effects, replacements and other future state changes are not fabricated.
"""
import argparse
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch

import heart_combat_pretraining as P

I, O, E = P.I, P.O, P.E
MODEL_TYPE = 'shared_item_heart_improvement'


def item_layout(x, spec):
    A = x.A
    deck = O.C.D.feature_spec(x)['deck_offset']
    relic = deck + 6 * A.CARD_CAP + 32
    positions = {raw: i for i, raw in enumerate(spec['observations'])}
    E.require(set(A._maxes[relic:relic+A.RELIC_CAP]) == {1.}, 'relic presence scale changed')
    E.require(set(A._maxes[deck+2*A.CARD_CAP:deck+4*A.CARD_CAP]) == {1000.}, 'card special scale changed')
    return dict(chosen=spec['state_width']+spec['descriptor_dim'], card_begin=A.OFF_CARD,
        cards=A.CARD_CAP, upgrade=A.OFF_CARD_UPGRADE, misc=A.OFF_CARD_MISC,
        relic_begin=A.OFF_RELIC, relics=A.RELIC_CAP,
        card_actions=[A.AK_REWARD_CARD, A.AK_SHOP_CARD],
        relic_actions=[A.AK_BOSS_RELIC, A.AK_REWARD_RELIC, A.AK_SHOP_RELIC],
        counts=[[positions[deck+2*i], positions[deck+2*i+1]] for i in range(A.CARD_CAP)],
        upgrade_sums=[positions[deck+2*A.CARD_CAP+i] for i in range(A.CARD_CAP)],
        misc_sums=[positions[deck+3*A.CARD_CAP+i] for i in range(A.CARD_CAP)],
        presence=[positions[relic+i] for i in range(A.RELIC_CAP)])


def route_items(features, layout):
    """Move eligible candidate ID tokens to learned inventory coordinates."""
    sparse = features.coalesce() if features.is_sparse else features.to_sparse().coalesce()
    rows, cols = sparse.indices()
    values = sparse.values()
    batch = features.shape[0]
    chosen = layout['chosen']
    card_rows = torch.zeros(batch, dtype=torch.bool, device=values.device)
    relic_rows = torch.zeros_like(card_rows)
    for kind in layout['card_actions']:
        card_rows[rows[cols == chosen+kind]] = True
    for kind in layout['relic_actions']:
        relic_rows[rows[cols == chosen+kind]] = True
    card = card_rows[rows] & (cols >= chosen+layout['card_begin']) & (cols < chosen+layout['card_begin']+layout['cards'])
    relic = relic_rows[rows] & (cols >= chosen+layout['relic_begin']) & (cols < chosen+layout['relic_begin']+layout['relics'])
    keep = ~(card | relic)
    new_indices, new_values = [sparse.indices()[:, keep]], [values[keep]]
    if bool(card.any()):
        upgrades = torch.zeros(batch, dtype=values.dtype, device=values.device)
        misc = torch.zeros_like(upgrades)
        for offset, target in ((layout['upgrade'], upgrades), (layout['misc'], misc)):
            selected = cols == chosen+offset
            target[rows[selected]] = values[selected]
        r = rows[card]
        ids = cols[card]-chosen-layout['card_begin']
        counts = torch.tensor(layout['counts'], device=values.device)[ids, (upgrades[r] > 0).long()]
        new_indices.append(torch.stack((r, counts))); new_values.append(values[card]/20.)
        for field, amount in (('upgrade_sums', upgrades[r]), ('misc_sums', misc[r])):
            target = torch.tensor(layout[field], device=values.device)[ids]
            new_indices.append(torch.stack((r, target))); new_values.append(values[card]*amount)
    if bool(relic.any()):
        r = rows[relic]
        ids = cols[relic]-chosen-layout['relic_begin']
        target = torch.tensor(layout['presence'], device=values.device)[ids]
        new_indices.append(torch.stack((r, target))); new_values.append(values[relic])
    return torch.sparse_coo_tensor(torch.cat(new_indices, 1), torch.cat(new_values),
        features.shape, check_invariants=True).coalesce()


def numpy_route(values, layout):
    """Independent dense arithmetic for review/native deployment checks."""
    result = values.copy()
    chosen = layout['chosen']
    for row, original in enumerate(values):
        kind = int(np.argmax(original[chosen:chosen+24]))
        if kind in layout['card_actions']:
            item = original[chosen+layout['card_begin']:chosen+layout['card_begin']+layout['cards']]
            upgrade, misc = original[chosen+layout['upgrade']], original[chosen+layout['misc']]
            for card in np.flatnonzero(item):
                result[row, layout['counts'][card][int(upgrade > 0)]] += item[card]/20.
                result[row, layout['upgrade_sums'][card]] += item[card]*upgrade
                result[row, layout['misc_sums'][card]] += item[card]*misc
                result[row, chosen+layout['card_begin']+card] = 0.
        if kind in layout['relic_actions']:
            item = original[chosen+layout['relic_begin']:chosen+layout['relic_begin']+layout['relics']]
            for relic in np.flatnonzero(item):
                result[row, layout['presence'][relic]] += item[relic]
                result[row, chosen+layout['relic_begin']+relic] = 0.
    return result


class ItemModel(I.ImprovementModel):
    def __init__(self, width, layout):
        super().__init__(width)
        self.item_layout = layout

    def forward(self, features):
        return super().forward(route_items(features, self.item_layout))


def warm_model(source, width, fold, inner, layout):
    directory = source / 'learning' / f'fold-{fold}'
    step = E.read(directory / 'auxiliary-report.json')['selected_steps']
    path = directory / (f'aux-inner-{step}.pt' if inner else 'auxiliary.pt')
    auxiliary = P.auxiliary_model(width, fold)
    auxiliary.load_state_dict(torch.load(path, weights_only=True, map_location='cpu'))
    P.reset_heart_head(auxiliary)
    model = ItemModel(width, layout)
    model.load_state_dict(auxiliary.state_dict())
    return model


def registered(root):
    reg = E.read(root / 'registration.json')
    E.require(reg['runner_sha256'] == E.sha(__file__), 'item-transfer runner changed')
    for path, digest in reg['hashes'].items():
        E.require(E.sha(path) == digest, 'bound source changed: '+path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['heart_recipe'] == I.RECIPE and plan['new_training_rollouts'] == 0, 'learning recipe changed')
    source = Path(plan['encoder_source'])
    review = E.read(source / 'auxiliary-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['passed'], 'encoder not admitted')
    E.require(review['learning_completion_sha256'] == E.sha(source / 'learning/completion.json'), 'wrong encoder completion')
    x = O.C.D.runtime(plan['runtime'])
    spec = E.read(Path(plan['learning_source']) / 'store/metadata.json')['spec']
    E.require(plan['item_layout'] == item_layout(x, spec), 'item layout changed')
    return plan


def train(root):
    plan = registered(root)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    examples = I.Examples(store, exact['observed_best'])
    source = Path(plan['encoder_source'])
    E.proof(source / 'learning', 'completion.json')
    out = root / 'learning'; out.mkdir()
    width = store.spec['width']+store.spec['descriptor_dim']
    base = torch.load(Path(plan['runtime']) / 'model.pt', weights_only=True, map_location='cpu')
    models, screens = [], []
    for fold in range(3):
        families = [f for f in examples.families if O.T.fold(f['seed']) != fold]
        inner, valid = O.inner_partition(families)
        roles = E.read(source / 'learning' / f'fold-{fold}/auxiliary-roles.json')
        E.require(roles['inner_train'] == [f['seed'] for f in inner] and roles['inner_validation'] == [f['seed'] for f in valid]
                  and roles['fit'] == [f['seed'] for f in families], 'warm encoder family roles differ')
        directory = out / f'fold-{fold}'; directory.mkdir()
        rng = np.random.default_rng(I.RECIPE['seed']+2000+fold)
        ids = examples.sample(valid, rng.random((I.RECIPE['validation_draws'], 3)))
        E.write(directory / 'actor-validation.json', dict(indices=ids.tolist(), inner_train=[f['seed'] for f in inner], inner_validation=[f['seed'] for f in valid]))
        model = warm_model(source, width, fold, True, plan['item_layout'])
        curve = []
        def checkpoint(step, current):
            curve.append(dict(step=step, loss=I.validation_loss(current, examples, ids, valid)))
            torch.save(current.state_dict(), directory / f'inner-{step}.pt')
        I.fit(model, examples, inner, I.RECIPE['steps'], fold, checkpoint)
        selected = min(curve, key=lambda r: (r['loss'], r['step']))['step']
        model = warm_model(source, width, fold, False, plan['item_layout'])
        I.fit(model, examples, families, selected, fold)
        fit_ids = np.concatenate([f['indices'] for f in families])
        support = sorted({store.identities[int(i)] for i in store.candidate_identity[store.edge_action[examples.edges[fit_ids]]].tolist()})
        path = directory / 'candidate.pt'
        torch.save(dict(model_type=MODEL_TYPE, actor_state=model.state_dict(), base_checkpoint=base,
            feature_spec=store.spec, paired_width=width, support=support, item_layout=plan['item_layout'], arm='shared_item',
            provenance=dict(fold=fold, fit_families=[f['seed'] for f in families], selected_actor_steps=selected,
                encoder_sha256=E.sha(source / 'learning' / f'fold-{fold}/auxiliary.pt'), recipe=I.RECIPE)), path)
        E.write(directory / 'stopping.json', curve)
        screen = I.branch_screen(model, examples, fold, support)
        E.write(directory / 'branch-screen.json', screen); screens.append(screen)
        models.append(dict(fold=fold, path=str(path), sha256=E.sha(path), selected_actor_steps=selected))
        print(dict(stage='heart', fold=fold, selected_steps=selected, screen=screen), flush=True)
    aggregate = {role: Counter() for role in ('fit', 'held')}
    for screen in screens:
        for role in aggregate: aggregate[role].update(screen[role])
    fitting, held = aggregate['fit'], aggregate['held']
    eligible = (fitting['known_gains'] >= .5*fitting['improvement_available']
                and fitting['known_gains'] > fitting['known_losses'] and held['known_gains'] > held['known_losses'])
    E.write(out / 'report.json', dict(status='complete', models=models, branch_screen={k: dict(v) for k, v in aggregate.items()},
        eligible_for_natural_evaluation=eligible, actor_optimizer_steps=3*I.RECIPE['steps']+sum(m['selected_actor_steps'] for m in models),
        auxiliary_optimizer_steps=0, new_training_rollouts=0, production_adoption=False))
    E.write(out / 'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))


class ItemPolicy(I.ImprovementPolicy):
    def __init__(self, checkpoint, x):
        torch.nn.Module.__init__(self)
        E.require(checkpoint['model_type'] == MODEL_TYPE, 'wrong item model')
        E.require(checkpoint['feature_spec'] == O.C.spec_for(x), 'public schema changed')
        self.x, self.spec = x, checkpoint['feature_spec']
        E.require(checkpoint['item_layout'] == item_layout(x, self.spec), 'public item mapping changed')
        E.require(checkpoint['paired_width'] == self.spec['width']+self.spec['descriptor_dim'], 'paired width changed')
        self.support = set(checkpoint['support'])
        self.base = x.H.load_scorer(checkpoint['base_checkpoint']).eval()
        self.actor = ItemModel(checkpoint['paired_width'], checkpoint['item_layout'])
        self.actor.load_state_dict(checkpoint['actor_state'])
        self.requires_grad_(False); self.eval()


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
        jobs.append(dict(mode='prefix', arm='shared_item', seed=seed, runtime=plan['runtime'], reference=refs[seed],
            checkpoint=str(checkpoint), checkpoint_sha256=E.sha(checkpoint), output=str(out / 'shared_item' / f'{seed}.json.gz')))
    deadline = time.monotonic() + plan['evaluation_timeout_seconds']
    rows = x.H.run_jobs(out, jobs, config, 'E168_full_runs', deadline, worker_fn=N.evaluate_worker)
    E.require(len(rows) == len(jobs) and [r['seed'] for r in rows] == seeds, 'assigned evaluation differs')
    faults = [dict(seed=r.get('seed'), status=r['status'], error=r.get('error')) for r in rows if r['status'] not in ('death', 'heart_win', 'act3_without_heart') or r.get('error')]
    E.write(out / 'faults.json', faults)
    E.require(not faults, 'evaluation fault; retain all assigned games')
    repeats = [dict(j, repeat=dict(path=j['output'], sha256=E.sha(j['output'])), output=str(out / 'repeated' / f'{j["seed"]}.json.gz')) for j, r in zip(jobs, rows) if r['status'] == 'heart_win']
    repeated = x.H.run_jobs(out, repeats, config, 'E168_winner_replans', deadline, worker_fn=N.evaluate_worker) if repeats else []
    E.require(len(repeated) == len(repeats) and all(r['status'] == 'heart_win' and r.get('fresh_replan_matched') for r in repeated), 'fresh winner replay failed')
    counts = x.B.paired_counts([int(refs[s]['status'] == 'heart_win') for s in seeds], [int(r['status'] == 'heart_win') for r in rows])
    E.write(out / 'report.json', dict(status='complete', families=128, parent_comparison=counts,
        gate_passed=counts['net_gain'] >= 8 and counts['exact_p'] < .025,
        natural_policy_evaluation_games=len(rows), winner_replans=len(repeats), zero_faults=True,
        new_training_rollouts=0, reserved_development_games=0, unseen_acceptance_games=0, production_adoption=False))
    paths = [Path(j['output']) for j in jobs + repeats] + [out / 'faults.json', out / 'report.json']
    E.write(out / 'completion-verification.json', dict(status='complete', zero_faults=True, hashes={str(p.relative_to(out)): E.sha(p) for p in paths}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('train', 'evaluate', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'train': train, 'evaluate': evaluate, 'check': registered}[args.command](args.study.resolve())
