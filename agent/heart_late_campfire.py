"""Bounded Act4 rest/smith continuations from existing natural parent traces."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import time

import heart_continuous_data as C

E = C.E


def registered(root):
    registration = E.read(root / 'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'late-campfire runner changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound input changed: ' + path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['families'] == 32 and plan['branches'] == 64, 'bounded pilot changed')
    review = E.read(Path(plan['learning_evidence']) / 'training-review.json')
    E.require(review['status'] == 'complete_reviewed' and not review['eligible_for_natural_evaluation'], 'preceding learning evidence changed')
    return plan


def candidates(x, gc, actions, descriptors, parent):
    if gc.act != 4 or gc.screen_state != x.R.sts.ScreenState.REST_ROOM:
        return None
    options = {int(a.idx1): i for i, (a, d) in enumerate(zip(actions, descriptors))
               if not a.is_potion_action and x.R.kind(d) == x.A.AK_REST and int(a.idx1) in (0, 1)}
    if set(options) != {0, 1} or parent not in options.values():
        return None
    return [options[0], options[1]]


def find_root(x, ref, parent):
    path = Path(ref['path'])
    E.require(E.sha(path) == ref['sha256'], 'natural source changed')
    run = E.read(path)
    E.require(run['seed'] == ref['seed'] and run['checkpoint_sha256'] == x.identity['model_sha256']
        and run['engine_sha256'] == x.identity['engine_sha256'], 'wrong source identity')
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    seen_campfire = False
    for index, step in enumerate(run['prefix']):
        x.R.clock_input(gc, x.config)
        E.require(x.R.fingerprint(gc) == step['before'], 'source state/RNG changed')
        if step['kind'] == 'outside' and gc.act == 4 and gc.screen_state == x.R.sts.ScreenState.REST_ROOM:
            seen_campfire = True
            actions = list(x.R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = x.A.build_choices(gc)
            observation = x.A.obs_vec(gc)
            chosen = parent.choose(gc, observation, actions, descriptors)
            E.require(int(actions[chosen].bits) == step['action'], 'source parent choice changed')
            options = candidates(x, gc, actions, descriptors, chosen)
            if options is not None:
                E.require(gc.red_key and gc.green_key and gc.blue_key, 'Act4 missing keys')
                return dict(id=f'{run["seed"]}-act4-campfire-{index}', seed=run['seed'], split='fit',
                    prefix_index=index, fingerprint=step['before'], act=gc.act, floor=gc.floor_num,
                    screen=gc.screen_state.name, category='act4_campfire', chosen=chosen,
                    teacher=x.R.heuristic_choice(gc, actions, descriptors),
                    actions=[int(a.bits) for a in actions], candidates=options,
                    option_names={str(options[0]): 'rest', str(options[1]): 'smith'},
                    observation=x.R.sparse(observation), descriptors=[x.R.sparse(d) for d in descriptors],
                    source_path=str(path), source_sha256=ref['sha256'], original_status=run['status']), 'eligible'
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config)
    x.P.verify_terminal(gc, run)
    return None, 'campfire_pair_ineligible' if seen_campfire else 'no_act4_campfire'


def prepare(root):
    plan = registered(root)
    x = C.D.runtime(plan['runtime'])
    parent = E.parent_model(x)
    source = Path(plan['natural_source'])
    roles = E.read(source / 'fit-roles.json')
    references = E.indexed(E.read(source / 'fit-references.json'), 'seed', 'reference')
    ordered = sorted(roles, key=lambda seed: hashlib.sha256(f'E162-act4-campfire:{seed}'.encode()).hexdigest())
    E.require(len(ordered) == 1536 and set(ordered) == set(references), 'source family roles changed')
    states, inventory = [], []
    for seed in ordered:
        state, reason = find_root(x, references[seed], parent)
        inventory.append(dict(seed=seed, reason=reason))
        if state is not None:
            states.append(state)
            print(dict(stage='existing_root', selected=len(states), scanned=len(inventory)), flush=True)
            if len(states) == plan['families']:
                break
    E.require(len(states) == plan['families'], 'too few eligible old roots; do not change selection or expand automatically')
    E.write(root / 'states-private.json', states)
    E.write(root / 'inventory-private.json', inventory)
    result = dict(status='complete', eligible_selected=len(states), scanned=len(inventory),
        total_existing_families=len(roles), unscanned=len(roles)-len(inventory),
        eligibility_counts=dict(Counter(r['reason'] for r in inventory)), new_games=0,
        selection='First32 eligible old families in prespecified hash order; terminal outcome is not an eligibility criterion.',
        hashes={str(p.name): E.sha(p) for p in (root / 'states-private.json', root / 'inventory-private.json')})
    E.write(root / 'preparation.json', result)
    print(result, flush=True)


def audit_parent_choices(x, row, state, candidate, parent):
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    count = 0
    for index, step in enumerate(row['prefix']):
        x.R.clock_input(gc, x.config)
        E.require(x.R.fingerprint(gc) == step['before'], 'audited state/RNG differs')
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = x.A.build_choices(gc)
            if index == state['prefix_index']:
                E.require(step['before'] == state['fingerprint'] and step['action'] == state['actions'][candidate], 'forced action differs')
            else:
                chosen = parent.choose(gc, x.A.obs_vec(gc), actions, descriptors)
                E.require(int(actions[chosen].bits) == step['action'], 'nonintervention choice differs from frozen parent')
                count += 1
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config)
    x.P.verify_terminal(gc, row)
    return count


def collect(root):
    plan = registered(root)
    E.proof(root, 'preparation.json')
    states = E.read(root / 'states-private.json')
    E.require(len(states) == 32, 'root denominator changed')
    x = C.D.runtime(plan['runtime'])
    parent = E.parent_model(x)
    jobs = [dict(mode='prefix', seed=state['seed'], state=state, candidate=candidate,
                 runtime=plan['runtime'], identity=x.identity, model=str(Path(plan['runtime']) / 'model.pt'),
                 output=str(root / 'branches' / f'{state["id"]}-{candidate}.json.gz'))
            for state in states for candidate in state['candidates']]
    E.require(len(jobs) == 64, 'branch count changed')
    E.write(root / 'jobs-private.json', jobs)
    deadline = time.monotonic() + plan['collection_timeout_seconds']
    # Reuse the previously verified generic collector. It runs every parent
    # control first, requiring a fresh planner to reproduce its full old path.
    E.run_branch_stage(x, root, jobs, 'E162_late_campfire', deadline)
    results, outside = [], 0
    for job in jobs:
        row = E.checked_branch(x, job)
        outside += audit_parent_choices(x, row, job['state'], job['candidate'], parent)
        results.append(row)
    repeats = [dict(job, output=str(root / 'repeated' / Path(job['output']).name))
               for job, row in zip(jobs, results) if row['status'] == 'heart_win']
    reruns = x.H.run_jobs(root, repeats, x.config, 'E162_winner_continuations', deadline, worker_fn=E.branch_worker) if repeats else []
    for job, row in zip(repeats, reruns):
        original = E.read(root / 'branches' / Path(job['output']).name)
        E.require(x.P.qualified(row, job['state'], job['candidate'], x.identity['model_sha256'])
            and row['status'] == original['status'] == 'heart_win'
            and row['prefix'] == original['prefix'] and x.P.terminal_signature(row) == x.P.terminal_signature(original), 'winner continuation differs')
    E.require(len(reruns) == len(repeats), 'missing winner repeat')
    pairs = []
    for state in states:
        rows = {j['candidate']: r for j, r in zip(jobs, results) if j['state']['id'] == state['id']}
        old = int(rows[state['chosen']]['status'] == 'heart_win')
        other = next(i for i in state['candidates'] if i != state['chosen'])
        new = int(rows[other]['status'] == 'heart_win')
        pairs.append(dict(seed=state['seed'], parent=old, alternative=new,
            parent_option=state['option_names'][str(state['chosen'])], alternative_option=state['option_names'][str(other)]))
    E.write(root / 'pairs-private.json', pairs)
    report = dict(status='complete', experiment='E162', families=32, branches=64,
        parent_wins=sum(p['parent'] for p in pairs), alternative_wins=sum(p['alternative'] for p in pairs),
        gains=sum(p['alternative'] > p['parent'] for p in pairs), losses=sum(p['alternative'] < p['parent'] for p in pairs),
        hindsight_available_wins=sum(max(p['alternative'], p['parent']) for p in pairs),
        nonintervention_nn_choices_verified=outside, fresh_winner_continuation_repeats=len(repeats),
        parent_controls_matched=32, zero_faults=True, optimizer_updates=0, production_adoption=False,
        limits='Conditional existing Act4 campfire roots, not natural population win rate. Source prefixes are replayed; suffixes use fresh frozen NN/MCTS. Each winner suffix is replanned again. No new seed families or automatic expansion.')
    E.write(root / 'report.json', report)
    paths = [Path(j['output']) for j in jobs+repeats] + [root / n for n in ('report.json', 'pairs-private.json', 'jobs-private.json', 'states-private.json', 'inventory-private.json', 'preparation.json')]
    E.write(root / 'completion.json', dict(status='complete', hashes={str(p.relative_to(root)): E.sha(p) for p in paths}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'collect', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'prepare': prepare, 'collect': collect, 'check': registered}[args.command](args.study.resolve())
