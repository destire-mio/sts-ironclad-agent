"""Bounded whole-game policy-gradient updates with matched stochastic execution.

The old greedy parent is a frozen logit reference. A trainable copy of its
card-context network supplies a zero-initialized residual. All new trajectories
are complete on-policy games on assigned historical families, never a search
for successful seeds. This is a distinct test, not a claim that E36/37 or E183
proved full-policy learning had never been attempted.
"""
import argparse
from collections import Counter
import copy
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import random
import time
import traceback

import numpy as np
import torch

import heart_whole_policy_search as W

E, C, N = W.E, W.C, W.N
RECIPE = dict(rounds=4, fit_families=128, evaluation_families=128, repeats=4,
    epochs=2, batch_size=128, learning_rate=3e-5, weight_decay=1e-5,
    clip_ratio=.2, reference_kl=.1, gradient_norm=1., seed=20260924191,
    initial_minimum_mixed=16, later_minimum_mixed=8, controls=4,
    calibration_families=32, calibration_change_fraction=.02,
    temperatures=[.03125, .0625, .125, .25, .5, 1., 2., 4., 8.])


def leave_one_out(rewards):
    rewards = np.asarray(rewards, dtype=np.float64)
    E.require(rewards.ndim == 1 and len(rewards) >= 2 and np.isin(rewards, [0., 1.]).all(),
              'invalid complete grouped returns')
    return rewards-(rewards.sum()-rewards)/(len(rewards)-1)


def distribution(scores):
    scores = np.asarray(scores, dtype=np.float64)
    E.require(scores.ndim == 1 and len(scores) and np.isfinite(scores).all(), 'invalid active logits')
    weights = np.exp(scores-scores.max())
    return weights/weights.sum()


def select(probabilities, uniform):
    probabilities = np.asarray(probabilities, dtype=np.float64)
    E.require(np.isfinite(probabilities).all() and (probabilities >= 0).all()
              and abs(probabilities.sum()-1) < 1e-10 and 0 <= uniform < 1, 'invalid sampling input')
    positive = np.flatnonzero(probabilities > 0)
    cumulative = np.cumsum(probabilities[positive]); cumulative[-1] = 1.
    return int(positive[np.searchsorted(cumulative, uniform, side='right')])


def stream_seed(role, family_index, iteration, repeat):
    # An external sampling assignment, not a network input or game RNG edit.
    key = f'E191:{RECIPE["seed"]}:{role}:{family_index}:{iteration}:{repeat}'
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)


class Policy:
    def __init__(self, x, state=None, temperature=1., sampling_seed=0, greedy=False):
        self.x = x; self.reference = W.WholePolicy(x)
        self.initial = copy.deepcopy(self.reference.base.base.net).double().requires_grad_(False)
        self.net = copy.deepcopy(self.initial).requires_grad_(True)
        if state is not None: self.net.load_state_dict(state)
        self.temperature = float(temperature); self.rng = random.Random(sampling_seed)
        self.greedy = greedy; self.samples = []
        E.require(self.temperature > 0 and np.isfinite(self.temperature), 'invalid temperature')

    @torch.no_grad()
    def menu(self, gc, observation, actions, descriptors):
        scores, _, parent = self.reference.menu(gc, observation, actions, descriptors)
        inner = self.reference.base.base
        raw = torch.cat((torch.tensor([observation]*len(actions)), torch.tensor(descriptors)), dim=1).float()
        features = inner.features(raw).double()
        active = np.flatnonzero(np.isfinite(scores))
        E.require(parent in active and len(active), 'parent lost legal support')
        f = features[active]
        residual = (self.net(f)-self.initial(f)).squeeze(-1).numpy()
        logits = (scores[active]+residual)/self.temperature
        probabilities = distribution(logits)
        return features[active], scores[active], active, parent, probabilities

    def choose(self, gc, observation, actions, descriptors):
        features, scores, active, parent, probabilities = self.menu(gc, observation, actions, descriptors)
        uniform = self.rng.random()  # exactly one independent draw per outside decision
        position = int(np.flatnonzero(active == parent)[0]) if self.greedy else select(probabilities, uniform)
        chosen = int(active[position])
        self.samples.append(dict(features=[self.x.R.sparse(row.tolist()) for row in features],
            base_scores=scores.tolist(), active=active.tolist(), parent=parent, chosen=chosen,
            chosen_active=position, probabilities=probabilities.tolist(),
            log_probability=float(np.log(probabilities[position])), uniform=uniform,
            action_kind=int(self.x.R.kind(descriptors[chosen]))))
        return chosen


def numpy_probabilities(policy, features, base_scores):
    def forward(net):
        state = net.state_dict(); values = np.asarray(features, dtype=np.float64)
        values = np.maximum(values @ state['0.weight'].numpy().T+state['0.bias'].numpy(), 0.)
        return (values @ state['2.weight'].numpy().T+state['2.bias'].numpy())[:, 0]
    return distribution((base_scores+forward(policy.net)-forward(policy.initial))/policy.temperature)


def objective(logits, records):
    logs = [values.log_softmax(0) for values in logits]
    selected = torch.stack([v[row['chosen_active']] for v, row in zip(logs, records, strict=True)])
    old = torch.tensor([r['log_probability'] for r in records], dtype=torch.float64)
    advantages = torch.tensor([r['advantage'] for r in records], dtype=torch.float64)
    ratios = (selected-old).exp()
    clipped = ratios.clamp(1-RECIPE['clip_ratio'], 1+RECIPE['clip_ratio'])
    pg = -torch.minimum(ratios*advantages, clipped*advantages).mean()
    kl = torch.stack([torch.nn.functional.kl_div(log, torch.tensor(row['probabilities'], dtype=torch.float64), reduction='sum')
                      for log, row in zip(logs, records, strict=True)]).mean()
    E.require(torch.isfinite(ratios).all() and torch.isfinite(pg) and torch.isfinite(kl), 'nonfinite policy objective')
    return pg+RECIPE['reference_kl']*kl, pg, kl, ratios


@lru_cache(maxsize=2)
def registered(root):
    registration = E.read(root/'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'policy-gradient program changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound policy-gradient source changed: '+path)
    plan = E.read(root/'protocol.json')
    E.require(plan['experiment'] == 'E191' and plan['recipe'] == RECIPE, 'policy-gradient recipe differs')
    prior = Path(plan['learning_evidence'])
    review = E.read(prior/'training-review.json')
    E.require(review['status'] == 'complete_reviewed' and not review['matched_auxiliary_gate_passed']
              and review['learning_completion_sha256'] == E.sha(prior/'learning/completion.json'),
              'completed prior learning evidence changed')
    roles = E.read(root/'roles-private.json')
    E.require(set(roles) == {'fit', 'evaluation'} and len(roles['fit']) == len(roles['evaluation']) == 128
              and len(set(roles['fit']+roles['evaluation'])) == 256, 'policy-gradient roles differ')
    E.proof(root/'calibration', 'completion.json')
    return plan


def load_policy(x, path, digest, temperature, seed, greedy=False):
    E.require(E.sha(path) == digest, 'policy-gradient actor changed')
    payload = torch.load(path, weights_only=True, map_location='cpu')
    E.require(payload['model_type'] == 'whole_stochastic_gradient' and payload['base_identity'] == x.identity
              and payload['recipe'] == RECIPE and payload['temperature'] == temperature, 'wrong policy payload')
    return Policy(x, payload['actor_state'], temperature, seed, greedy)


def audit_route(x, run, policy, sampling_seed):
    E.require(run['status'] in ('heart_win', 'death', 'act3_without_heart') and not run.get('error'),
              'execution fault is not a return')
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    generator = random.Random(sampling_seed); choices = 0; changes = Counter(); bosses = []; fourth = []
    maximum = 0.
    for step in run['prefix']:
        x.R.clock_input(gc, x.config); before = x.R.fingerprint(gc)
        E.require(before == step['before'], 'recorded game state/RNG differs')
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc)); _, ds, _ = x.A.build_choices(gc)
            features, scores, active, parent, probabilities = policy.menu(gc, x.A.obs_vec(gc), actions, ds)
            row = policy.samples[choices]
            E.require(row['features'] == [x.R.sparse(v.tolist()) for v in features]
                      and row['base_scores'] == scores.tolist() and row['active'] == active.tolist()
                      and row['parent'] == parent, 'recorded training inputs differ from native state')
            independent = numpy_probabilities(policy, features.numpy(), scores)
            maximum = max(maximum, float(np.max(np.abs(independent-probabilities))))
            np.testing.assert_allclose(independent, probabilities, atol=1e-10, rtol=0)
            np.testing.assert_allclose(probabilities, row['probabilities'], atol=1e-12, rtol=0)
            u = generator.random(); E.require(u == row['uniform'], 'policy sampling stream differs')
            # Independent linear scan of the categorical CDF.
            cumulative = 0.; position = int(np.flatnonzero(independent > 0)[-1])
            for j, amount in enumerate(independent):
                cumulative += float(amount)
                if u < cumulative:
                    position = j; break
            chosen = parent if policy.greedy else int(active[position])
            E.require(chosen == row['chosen'] and int(actions[chosen].bits) == step['action'], 'sampled deployed action differs')
            E.require(row['chosen_active'] == int(np.flatnonzero(active == chosen)[0])
                      and abs(row['log_probability']-np.log(probabilities[row['chosen_active']])) < 1e-12,
                      'recorded behavior likelihood differs')
            E.require(before == x.R.fingerprint(gc), 'scoring changed game state/RNG')
            if chosen != parent: changes[str(x.R.kind(ds[chosen]))] += 1
            choices += 1
        else:
            if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS: bosses.append(gc.encounter.name)
            if gc.act == 4:
                E.require(gc.red_key and gc.green_key and gc.blue_key, 'Act4 keys missing')
                fourth.append(gc.encounter.name)
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run)
    E.require(choices == len(policy.samples), 'outside training record count differs')
    if run['status'] == 'heart_win':
        E.require(len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART'],
                  'incomplete A20 Heart chain')
    return dict(outside_choices=choices, changes=dict(changes), maximum_probability_error=maximum,
                public_inputs_sampling_state_rng_and_terminal_verified=True)


def worker(job, config):
    try:
        root = Path(job['study']); plan = registered(root); x = C.D.runtime(plan['runtime'])
        torch.set_num_threads(1)
        policy = load_policy(x, job['policy'], job['policy_sha256'], job['temperature'], job['sampling_seed'], job.get('control', False))
        E.require(E.sha(job['reference']['path']) == job['reference']['sha256'], 'reference changed')
        reference = E.read(job['reference']['path'])
        E.require(reference['seed'] == job['seed'] and reference['engine_sha256'] == x.identity['engine_sha256']
                  and reference['checkpoint_sha256'] == x.identity['model_sha256'], 'reference family/runtime differs')
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
        run = x.R.rollout(job['seed'], config, gc=gc, net=policy, record=True, record_samples=False)
        x.R.clock_input(gc, config)
        run.update(terminal_fingerprint=x.R.fingerprint(gc), checkpoint_sha256=job['policy_sha256'],
            engine_sha256=x.identity['engine_sha256'], policy_sampling_seed=job['sampling_seed'],
            search_budget=dict(simulations=8000, boss_multiplier=3, max_replans=256))
        run['audit'] = audit_route(x, run, policy, job['sampling_seed'])
        run['first_change'] = N.first_change(x, reference, run)
        if job.get('control'):
            E.require(run['prefix'] == reference['prefix'] and x.P.terminal_signature(run) == x.P.terminal_signature(reference),
                      'fresh greedy parent control differs')
        if job.get('repeat'):
            previous = E.read(job['repeat']['path'])
            E.require(E.sha(job['repeat']['path']) == job['repeat']['sha256'] and run['status'] == previous['status'] == 'heart_win'
                      and run['prefix'] == previous['prefix'] and x.P.terminal_signature(run) == x.P.terminal_signature(previous),
                      'stochastic winner replan differs')
            run['fresh_replan_matched'] = True
        run['policy_samples'] = policy.samples
        result = run
    except Exception:
        result = dict(status='evaluation_error', seed=job['seed'], error=traceback.format_exc())
    output = Path(job['output']); output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name+'.tmp')
    with gzip.open(temporary, 'wt') as stream: json.dump(result, stream, separators=(',', ':'))
    temporary.replace(output)


def execute(x, out, jobs, config, name, deadline):
    rows = x.H.run_jobs(out, jobs, config, name, deadline, worker_fn=worker)
    E.require(len(rows) == len(jobs) and all(r['status'] in ('heart_win', 'death', 'act3_without_heart') and not r.get('error') for r in rows),
              'incomplete or faulty on-policy cohort; no return substitution')
    repeats = [dict(job, repeat=dict(path=job['output'], sha256=E.sha(job['output'])),
                    output=str(Path(job['output']).parent/'repeated'/Path(job['output']).name))
               for job, row in zip(jobs, rows, strict=True) if row['status'] == 'heart_win' and not job.get('control')]
    repeated = x.H.run_jobs(out, repeats, config, name+'_winner_replans', deadline, worker_fn=worker) if repeats else []
    E.require(len(repeated) == len(repeats) and all(r.get('fresh_replan_matched') for r in repeated), 'winner replan missing')
    E.write(out/(name+'-completion.json'), dict(status='complete', games=len(jobs), winner_replans=len(repeats),
        hashes={j['output']: E.sha(j['output']) for j in jobs+repeats}))
    return rows, len(repeats)


def fit(policy, rows, iteration, families, collecting_sha):
    E.require(len(rows) == RECIPE['fit_families']*RECIPE['repeats'], 'on-policy batch is not complete')
    E.require(len(families) == len(set(families)) == RECIPE['fit_families']
              and [r['seed'] for r in rows] == [seed for seed in families for _ in range(RECIPE['repeats'])],
              'on-policy fitting family or order differs')
    E.require(all(r['checkpoint_sha256'] == collecting_sha and not r.get('error')
                  and r['status'] in ('heart_win', 'death', 'act3_without_heart')
                  and r['audit']['public_inputs_sampling_state_rng_and_terminal_verified'] for r in rows),
              'unverified or off-policy data cannot enter the update')
    records = []; mixed = 0
    for start in range(0, len(rows), RECIPE['repeats']):
        group = rows[start:start+RECIPE['repeats']]
        E.require(len({r['seed'] for r in group}) == 1, 'return baseline crossed game family')
        E.require(len({r['policy_sampling_seed'] for r in group}) == RECIPE['repeats'], 'duplicate behavior sampling stream')
        rewards = [int(r['status'] == 'heart_win') for r in group]
        mixed += int(len(set(rewards)) > 1)
        for row, advantage in zip(group, leave_one_out(rewards), strict=True):
            for sample in row['policy_samples']:
                if len(sample['active']) > 1: records.append(dict(sample, advantage=float(advantage)))
    required = RECIPE['initial_minimum_mixed'] if iteration == 0 else RECIPE['later_minimum_mixed']
    if mixed < required:
        return dict(updated=False, reason='insufficient_mixed_family_signal', mixed_families=mixed, required=required,
                    optimizer_updates=0, decisions=len(records))
    optimizer = torch.optim.AdamW(policy.net.parameters(), lr=RECIPE['learning_rate'], weight_decay=RECIPE['weight_decay'])
    generator = random.Random(RECIPE['seed']+1000+iteration); updates = 0; curve = []; maximum_gradient = 0.
    width = policy.net[0].in_features
    for epoch in range(RECIPE['epochs']):
        order = list(range(len(records))); generator.shuffle(order); totals = Counter()
        for at in range(0, len(order), RECIPE['batch_size']):
            batch = [records[i] for i in order[at:at+RECIPE['batch_size']]]
            lengths = [len(r['active']) for r in batch]
            values = np.zeros((sum(lengths), width), dtype=np.float64); cursor = 0
            for row in batch:
                for features in row['features']:
                    for col, value in features: values[cursor, col] = value
                    cursor += 1
            features = torch.from_numpy(values)
            reference = policy.initial(features).detach().squeeze(-1)
            residual = (policy.net(features).squeeze(-1)-reference).split(lengths)
            logits = [(torch.tensor(row['base_scores'], dtype=torch.float64)+v)/policy.temperature
                      for row, v in zip(batch, residual, strict=True)]
            loss, pg, kl, ratios = objective(logits, batch)
            optimizer.zero_grad(set_to_none=True); loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(policy.net.parameters(), RECIPE['gradient_norm'])
            E.require(torch.isfinite(norm), 'nonfinite policy gradient')
            maximum_gradient = max(maximum_gradient, float(norm))
            optimizer.step(); updates += 1
            totals['decisions'] += len(batch); totals['policy_loss'] += float(pg.detach())*len(batch)
            totals['kl'] += float(kl.detach())*len(batch)
            totals['clipped'] += int(((ratios.detach()-1).abs() > RECIPE['clip_ratio']).sum())
        curve.append(dict(epoch=epoch, decisions=totals['decisions'], policy_loss=totals['policy_loss']/totals['decisions'],
                          kl=totals['kl']/totals['decisions'], clip_fraction=totals['clipped']/totals['decisions']))
    return dict(updated=True, mixed_families=mixed, optimizer_updates=updates, decisions=len(records),
                nonzero_advantage_decisions=sum(r['advantage'] != 0 for r in records),
                maximum_gradient_norm=maximum_gradient, curve=curve)


def run(root):
    plan = registered(root)
    E.require(E.read(root/'preflight.json')['status'] == 'passed', 'whole-policy preflight missing')
    x = C.D.runtime(plan['runtime']); torch.set_num_threads(1)
    config = dict(x.config, workers=8)
    # The byte-identical frozen engine retains its native 256-replan guard;
    # the historical Python config and exposed binding have no such argument.
    E.require(config['ascension'] == 20 and config['simulations'] == 8000 and config['boss_multiplier'] == 3,
              'frozen combat budget changed')
    roles = E.read(root/'roles-private.json')
    references = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    temperature = E.read(root/'calibration/report.json')['temperature']
    policy = Policy(x, temperature=temperature)
    out = root/'learning'; out.mkdir(); deadline = time.monotonic()+plan['timeout_seconds']
    games = 0; repeats = 0; reports = []

    def save(name):
        path = out/name
        torch.save(dict(model_type='whole_stochastic_gradient', actor_state=policy.net.state_dict(),
            base_identity=x.identity, recipe=RECIPE, temperature=temperature), path)
        return path, E.sha(path)

    def job(seed, index, role, iteration, repeat, path, digest, folder, **extra):
        return dict(mode='prefix', study=str(root), seed=seed, reference=references[seed], policy=str(path),
            policy_sha256=digest, temperature=temperature, sampling_seed=stream_seed(role,index,iteration,repeat),
            output=str(out/folder/f'{index}-{repeat}.json.gz'), **extra)

    initial, initial_sha = save('initial.pt')
    controls = [job(seed, i, 'control', 0, 0, initial, initial_sha, 'controls', control=True)
                for i, seed in enumerate(roles['fit'][:RECIPE['controls']])]
    execute(x, out, controls, config, 'controls', deadline); games += len(controls)
    actor, digest = initial, initial_sha
    for iteration in range(RECIPE['rounds']):
        jobs = [job(seed, i, 'fit', iteration, rep, actor, digest, f'round-{iteration}/episodes')
                for i, seed in enumerate(roles['fit']) for rep in range(RECIPE['repeats'])]
        rows, count = execute(x, out, jobs, config, f'round_{iteration}', deadline)
        games += len(rows); repeats += count
        before = {k: v.clone() for k, v in policy.net.state_dict().items()}
        result = fit(policy, rows, iteration, roles['fit'], digest)
        result.update(iteration=iteration, collection_actor_sha256=digest,
                      sampled_training_wins=sum(r['status'] == 'heart_win' for r in rows),
                      games=len(rows), winner_replans=count)
        actor, digest = save(f'actor-after-{iteration}.pt')
        result['updated_actor_sha256'] = digest
        result['parameters_changed'] = any(not torch.equal(before[k], v) for k, v in policy.net.state_dict().items())
        E.require(result['updated'] == result['parameters_changed'], 'claimed update and actor disagree')
        E.write(out/f'round-{iteration}/update.json', result); reports.append(result)
        print(result, flush=True)
        del rows
        if not result['updated']: break
    final, final_sha = save('candidate.pt')
    updated = any(r['updated'] for r in reports); comparison = None; parent_comparison = None
    if updated:
        evaluations = {}
        for label, path, digest in [('initial', initial, initial_sha), ('candidate', final, final_sha)]:
            jobs = [job(seed, i, 'evaluation', 0, 0, path, digest, 'evaluation/'+label)
                    for i, seed in enumerate(roles['evaluation'])]
            rows, count = execute(x, out, jobs, config, 'evaluation_'+label, deadline)
            games += len(rows); repeats += count
            evaluations[label] = [int(r['status'] == 'heart_win') for r in rows]
        comparison = x.B.paired_counts(evaluations['initial'], evaluations['candidate'])
        parent_comparison = x.B.paired_counts([int(references[s]['status'] == 'heart_win') for s in roles['evaluation']], evaluations['candidate'])
    passed = bool(updated and all(r['net_gain'] >= 8 and r['exact_p'] < .025 for r in [comparison, parent_comparison]))
    report = dict(status='complete', experiment='E191', training_rounds=len(reports),
        optimizer_updates=sum(r['optimizer_updates'] for r in reports), parameter_updates=sum(r['updated'] for r in reports),
        trainable_parameters=sum(p.numel() for p in policy.net.parameters()), temperature=temperature,
        stochastic_baseline_comparison=comparison, greedy_parent_comparison=parent_comparison,
        learning_gate_passed=passed, new_games=games+repeats, base_games=games, winner_replans=repeats,
        candidate_sha256=final_sha, zero_faults=True, policy_adoption=False, unused_acceptance_games=0, limits=plan['limits'])
    E.write(out/'report.json', report)
    E.write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    run(parser.parse_args().study.resolve())
