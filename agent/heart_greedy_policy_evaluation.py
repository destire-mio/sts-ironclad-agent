"""Evaluate one frozen post-hoc greedy interpretation of E191.

Only the 48 already-certified changed historical routes need new outcomes.
The other 80 retain their fully replayed parent route. This is an execution
comparison of existing learned weights, not new training or final acceptance.
"""
import argparse
from collections import Counter
from functools import lru_cache
import gzip
import json
from pathlib import Path
import time
import traceback

import numpy as np
import torch

import heart_whole_policy_gradient as G

E = G.E


def greedy_position(logits, active, parent):
    values = np.asarray(logits, dtype=np.float64)
    active = np.asarray(active, dtype=np.int64)
    E.require(values.ndim == 1 and values.shape == active.shape and len(active)
              and len(set(active.tolist())) == len(active) and np.isfinite(values).all()
              and parent in active, 'invalid greedy support')
    tied = np.flatnonzero(values.max()-values <= 1e-9)
    parent_position = int(np.flatnonzero(active == parent)[0])
    return parent_position if parent_position in tied else int(tied[0])


class Policy(G.Policy):
    def choose(self, gc, observation, actions, descriptors):
        features, scores, active, parent, _ = self.menu(gc, observation, actions, descriptors)
        with torch.no_grad():
            logits = scores+(self.net(features)-self.initial(features)).flatten().numpy()
        chosen = int(active[greedy_position(logits, active, parent)])
        self.samples.append(dict(parent=parent, chosen=chosen, active=active.tolist(), logits=logits.tolist(),
                                 action_kind=int(self.x.R.kind(descriptors[chosen]))))
        return chosen


def policy_from(x, path, digest):
    E.require(E.sha(path) == digest, 'greedy evaluation checkpoint changed')
    payload = torch.load(path, weights_only=True, map_location='cpu')
    E.require(payload['model_type'] == 'whole_stochastic_gradient' and payload['base_identity'] == x.identity
              and payload['recipe'] == G.RECIPE and payload['temperature'] == 1., 'wrong learned policy')
    return Policy(x, payload['actor_state'], temperature=1.)


def numpy_choice(policy, features, scores, active, parent):
    def forward(state):
        hidden = np.maximum(features @ state['0.weight'].numpy().T+state['0.bias'].numpy(), 0.)
        return (hidden @ state['2.weight'].numpy().T+state['2.bias'].numpy())[:, 0]
    logits = scores+forward(policy.net.state_dict())-forward(policy.initial.state_dict())
    maximum = max(float(v) for v in logits)
    candidates = [int(i) for i, v in zip(active, logits, strict=True) if maximum-float(v) <= 1e-9]
    return parent if parent in candidates else candidates[0], logits


@lru_cache(maxsize=2)
def registered(root):
    registration = E.read(root/'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'greedy evaluation program changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound greedy evaluation input changed: '+path)
    plan = E.read(root/'protocol.json')
    E.require(plan['experiment'] == 'E192' and plan['budget'] == dict(changed_routes=48, controls=4,
        base_games_max=52, winner_replans_max=48, total_games_max=100, workers=8), 'changed evaluation budget')
    source = Path(plan['learning_source'])
    G.registered(source)
    review = E.read(source/'result-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['result']['optimizer_updates'] == 3444
              and not review['result']['learning_gate_passed']
              and review['completion_sha256'] == E.sha(source/'learning/completion.json'), 'completed learning review missing')
    audit = E.read(source/'greedy-path-audit-private.json')
    E.require(audit['result']['status'] == 'complete' and audit['result']['counts']['changed_routes'] == 48
              and audit['result']['counts']['unchanged_complete_routes'] == 80
              and audit['result']['candidate_sha256'] == E.sha(source/'learning/candidate.pt'), 'greedy path certificate differs')
    assignments = E.read(root/'assignments-private.json')
    expected = [r['evaluation_index'] for r in audit['paths'] if r['first_change'] is not None]
    unchanged = [r['evaluation_index'] for r in audit['paths'] if r['first_change'] is None]
    E.require(assignments['changed'] == expected and assignments['unchanged'] == unchanged, 'route assignments changed')
    controls = [r['evaluation_index'] for r in audit['paths'] if r['first_change'] is None and r['parent_status'] == 'heart_win'][:2]
    controls += [r['evaluation_index'] for r in audit['paths'] if r['first_change'] is None and r['parent_status'] != 'heart_win'][:2]
    E.require(assignments['controls'] == controls and len(controls) == 4, 'unchanged controls changed')
    return plan


def audit_route(x, run, policy):
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    changes = Counter()
    choices = 0
    maximum = 0.
    bosses, fourth = [], []
    for step in run['prefix']:
        x.R.clock_input(gc, x.config)
        before = x.R.fingerprint(gc)
        E.require(before == step['before'], 'greedy evaluation state/RNG differs')
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = x.A.build_choices(gc)
            features, scores, active, parent, _ = policy.menu(gc, x.A.obs_vec(gc), actions, descriptors)
            selected, independent = numpy_choice(policy, features.numpy(), scores, active, parent)
            row = policy.samples[choices]
            maximum = max(maximum, float(np.abs(independent-row['logits']).max()))
            np.testing.assert_allclose(independent, row['logits'], rtol=0, atol=1e-9)
            E.require(row['active'] == active.tolist() and row['parent'] == parent and row['chosen'] == selected
                      and int(actions[selected].bits) == step['action'] and row['action_kind'] == x.R.kind(descriptors[selected]),
                      'greedy learned score or deployed action differs')
            E.require(before == x.R.fingerprint(gc), 'greedy scoring changed game RNG/state')
            if selected != parent:
                changes[f'{gc.act}:{row["action_kind"]}'] += 1
            choices += 1
        else:
            if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS:
                bosses.append(gc.encounter.name)
            if gc.act == 4:
                E.require(gc.red_key and gc.green_key and gc.blue_key, 'Act4 key missing')
                fourth.append(gc.encounter.name)
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config)
    x.P.verify_terminal(gc, run)
    E.require(choices == len(policy.samples), 'greedy choice count differs')
    if run['status'] == 'heart_win':
        E.require(len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART'], 'incomplete Heart chain')
    return dict(public_inputs_actions_state_rng_and_terminal_verified=True, outside_choices=choices,
                changes=dict(changes), maximum_numpy_logit_error=maximum)


def worker(job, config):
    run = None
    try:
        root = Path(job['study'])
        plan = registered(root)
        x = G.C.D.runtime(plan['runtime'])
        torch.set_num_threads(1)
        policy = policy_from(x, plan['candidate'], plan['candidate_sha256'])
        E.require(E.sha(job['reference']['path']) == job['reference']['sha256'], 'greedy route reference changed')
        reference = E.read(job['reference']['path'])
        E.require(reference['seed'] == job['seed'] and reference['engine_sha256'] == x.identity['engine_sha256']
                  and reference['checkpoint_sha256'] == x.identity['model_sha256'], 'wrong parent family/runtime')
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
        run = x.R.rollout(job['seed'], config, gc=gc, net=policy, record=True, record_samples=False)
        E.require(run['status'] in ('heart_win', 'death', 'act3_without_heart') and not run.get('error'), 'fault is not a terminal label')
        x.R.clock_input(gc, config)
        run.update(terminal_fingerprint=x.R.fingerprint(gc), checkpoint_sha256=plan['candidate_sha256'],
                   engine_sha256=x.identity['engine_sha256'], execution_rule='learned_greedy_parent_ties',
                   search_budget=dict(simulations=8000, boss_multiplier=3, max_replans=256))
        run['audit'] = audit_route(x, run, policy)
        run['policy_samples'] = policy.samples
        run['first_change'] = G.N.first_change(x, reference, run)
        expected = dict(kind='unchanged') if job.get('control') else dict(kind='noncombat', prefix_index=job['first_change']['prefix_index'])
        E.require(run['first_change'] == expected, 'fresh route disagrees with old-path greedy certificate')
        if job.get('repeat'):
            E.require(E.sha(job['repeat']['path']) == job['repeat']['sha256'], 'greedy winner changed')
            previous = E.read(job['repeat']['path'])
            E.require(run['status'] == previous['status'] == 'heart_win' and run['prefix'] == previous['prefix']
                      and run['policy_samples'] == previous['policy_samples']
                      and x.P.terminal_signature(run) == x.P.terminal_signature(previous), 'greedy winner fresh replan differs')
            run['fresh_replan_matched'] = True
        result = run
    except Exception:
        result = dict(status='evaluation_error', seed=job['seed'], error=traceback.format_exc())
        if run is not None:
            result['partial_run'] = run
    output = Path(job['output'])
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name+'.tmp')
    with gzip.open(temporary, 'wt') as stream:
        json.dump(result, stream, separators=(',', ':'))
    temporary.replace(output)


def run(root):
    plan = registered(root)
    E.require(E.read(root/'preflight.json')['status'] == 'passed', 'greedy execution preflight missing')
    x = G.C.D.runtime(plan['runtime'])
    torch.set_num_threads(1)
    config = dict(x.config, workers=8)
    E.require(config['ascension'] == 20 and config['simulations'] == 8000 and config['boss_multiplier'] == 3, 'combat budget changed')
    source = Path(plan['learning_source'])
    roles = E.read(source/'roles-private.json')
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    assignments = E.read(root/'assignments-private.json')
    audit = E.read(source/'greedy-path-audit-private.json')
    out = root/'evaluation'
    out.mkdir()
    deadline = time.monotonic()+plan['timeout_seconds']

    def job(index, control=False):
        seed = roles['evaluation'][index]
        return dict(mode='prefix', study=str(root), seed=seed, evaluation_index=index, control=control,
                    first_change=audit['paths'][index]['first_change'], reference=refs[seed],
                    output=str(out/('controls' if control else 'candidate')/f'{index}.json.gz'))

    def execute(jobs, name):
        rows = x.H.run_jobs(out, jobs, config, name, deadline, worker_fn=worker)
        E.require(len(rows) == len(jobs) and all(r['status'] in ('heart_win', 'death', 'act3_without_heart') and not r.get('error') for r in rows),
                  'incomplete/faulty greedy evaluation; no result substitution')
        return rows

    controls = [job(i, True) for i in assignments['controls']]
    execute(controls, 'unchanged_controls')
    jobs = [job(i) for i in assignments['changed']]
    rows = execute(jobs, 'changed_routes')
    repeated_jobs = [dict(job, repeat=dict(path=job['output'], sha256=E.sha(job['output'])),
                          output=str(Path(job['output']).parent/'repeated'/Path(job['output']).name))
                     for job, row in zip(jobs, rows, strict=True) if row['status'] == 'heart_win']
    repeated = execute(repeated_jobs, 'winner_replans') if repeated_jobs else []
    E.require(all(r.get('fresh_replan_matched') for r in repeated), 'missing greedy winner proof')
    old = [int(refs[s]['status'] == 'heart_win') for s in roles['evaluation']]
    candidate = old.copy()
    for index, row in zip(assignments['changed'], rows, strict=True):
        candidate[index] = int(row['status'] == 'heart_win')
    comparison = x.B.paired_counts(old, candidate)
    passed = comparison['net_gain'] >= 8 and comparison['exact_p'] < .025
    report = dict(status='complete', experiment='E192', comparison=comparison, learning_gate_passed=passed,
        changed_routes_evaluated=len(rows), unchanged_routes_reused=len(assignments['unchanged']),
        unchanged_controls=len(controls), base_games=len(jobs)+len(controls), winner_replans=len(repeated),
        new_games=len(jobs)+len(controls)+len(repeated), optimizer_updates=0,
        source_optimizer_updates=3444, candidate_sha256=plan['candidate_sha256'],
        zero_faults=True, policy_adoption=False, unused_acceptance_games=0, limits=plan['limits'])
    E.write(out/'report.json', report)
    E.write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    run(parser.parse_args().study.resolve())
