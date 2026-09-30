"""Bounded Act2 boss-relic comparisons from admitted natural parent traces."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import time

import heart_late_campfire as L

C, E = L.C, L.E
audit_parent_choices = L.audit_parent_choices


def registered(root):
    registration = E.read(root / 'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'second-boss runner changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound input changed: ' + path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['families'] == 32 and plan['maximum_branches'] == 128
              and plan['minimum_rescuable_families_for_learning'] == 8, 'bounded pilot changed')
    review = E.read(Path(plan['learning_evidence']) / 'training-review.json')
    E.require(review['status'] == 'complete_reviewed' and not review['eligible_for_natural_evaluation'],
              'preceding learning evidence changed')
    return plan


def candidates(x, gc, actions, descriptors, parent):
    if gc.act != 2 or gc.screen_state != x.R.sts.ScreenState.BOSS_RELIC_REWARDS:
        return None
    E.require(len(actions) == len(descriptors), 'action/descriptor alignment changed')
    options = []
    for index, (action, descriptor) in enumerate(zip(actions, descriptors)):
        if action.is_potion_action:
            continue
        kind, slot = x.R.kind(descriptor), int(action.idx1)
        E.require((kind == x.A.AK_BOSS_RELIC and 0 <= slot < len(gc.boss_relics))
                  or (kind == x.A.AK_BOSS_SKIP and slot == 3), 'unknown boss-menu action')
        options.append(index)
    E.require(2 <= len(options) <= 4 and len({int(actions[i].idx1) for i in options}) == len(options),
              'unexpected boss-menu capacity or duplicate option')
    return options if parent in options else None


def find_root(x, ref, parent):
    path = Path(ref['path'])
    E.require(E.sha(path) == ref['sha256'], 'natural source changed')
    run = E.read(path)
    E.require(run['seed'] == ref['seed'] and run['checkpoint_sha256'] == x.identity['model_sha256']
              and run['engine_sha256'] == x.identity['engine_sha256'], 'wrong source identity')
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    seen_menu = False
    for index, step in enumerate(run['prefix']):
        x.R.clock_input(gc, x.config)
        E.require(x.R.fingerprint(gc) == step['before'], 'source state/RNG changed')
        if step['kind'] == 'outside' and gc.act == 2 and gc.screen_state == x.R.sts.ScreenState.BOSS_RELIC_REWARDS:
            seen_menu = True
            actions = list(x.R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = x.A.build_choices(gc)
            observation = x.A.obs_vec(gc)
            chosen = parent.choose(gc, observation, actions, descriptors)
            E.require(int(actions[chosen].bits) == step['action'], 'source parent choice changed')
            options = candidates(x, gc, actions, descriptors, chosen)
            if options is not None:
                names = {str(i): ('skip' if x.R.kind(descriptors[i]) == x.A.AK_BOSS_SKIP
                                  else str(gc.boss_relics[int(actions[i].idx1)])) for i in options}
                return dict(id=f'{run["seed"]}-act2-boss-relic-{index}', seed=run['seed'], split='fit',
                    prefix_index=index, fingerprint=step['before'], act=gc.act, floor=gc.floor_num,
                    screen=gc.screen_state.name, category='act2_boss_relic', chosen=chosen,
                    teacher=x.R.heuristic_choice(gc, actions, descriptors),
                    actions=[int(a.bits) for a in actions], candidates=options, option_names=names,
                    observation=x.R.sparse(observation), descriptors=[x.R.sparse(d) for d in descriptors],
                    source_path=str(path), source_sha256=ref['sha256'], original_status=run['status']), 'eligible'
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config)
    x.P.verify_terminal(gc, run)
    return None, 'boss_menu_parent_ineligible' if seen_menu else 'no_act2_boss_relic'


def prepare(root):
    plan = registered(root)
    x = C.D.runtime(plan['runtime'])
    parent = E.parent_model(x)
    source = Path(plan['natural_source'])
    roles = E.read(source / 'fit-roles.json')
    references = E.indexed(E.read(source / 'fit-references.json'), 'seed', 'reference')
    ordered = sorted(roles, key=lambda seed: hashlib.sha256(f'E167-act2-boss-relic:{seed}'.encode()).hexdigest())
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
    E.require(len(states) == plan['families'], 'too few eligible roots; no automatic expansion or changed selection')
    E.write(root / 'states-private.json', states)
    E.write(root / 'inventory-private.json', inventory)
    result = dict(status='complete', eligible_selected=len(states), scanned=len(inventory),
        total_existing_families=len(roles), unscanned=len(roles)-len(inventory),
        branches=sum(len(s['candidates']) for s in states),
        eligibility_counts=dict(Counter(r['reason'] for r in inventory)), new_games=0,
        selection='First32 eligible old families in fixed hash order; no filtering by terminal outcome.',
        hashes={p.name: E.sha(p) for p in (root / 'states-private.json', root / 'inventory-private.json')})
    E.write(root / 'preparation.json', result)
    print(result, flush=True)


def summarize(pairs):
    """Keep multiple measured alternatives separate; no arbitrary alternative policy."""
    return dict(parent_wins=sum(p['outcomes'][str(p['parent_candidate'])] for p in pairs),
        winning_branches=sum(sum(p['outcomes'].values()) for p in pairs),
        rescuable_families=sum(not p['outcomes'][str(p['parent_candidate'])] and any(p['outcomes'].values()) for p in pairs),
        parent_winners_with_losing_alternative=sum(bool(p['outcomes'][str(p['parent_candidate'])])
                                                  and not all(p['outcomes'].values()) for p in pairs),
        hindsight_available_wins=sum(any(p['outcomes'].values()) for p in pairs),
        all_options_win=sum(all(p['outcomes'].values()) for p in pairs),
        all_options_lose=sum(not any(p['outcomes'].values()) for p in pairs))


def collect(root):
    plan = registered(root)
    E.proof(root, 'preparation.json')
    states = E.read(root / 'states-private.json')
    E.require(len(states) == len({s['seed'] for s in states}) == 32, 'root denominator changed')
    x = C.D.runtime(plan['runtime'])
    parent = E.parent_model(x)
    E.require(x.config['simulations'] == 8000 and x.config['boss_multiplier'] == 3
              and x.config['workers'] == 8 and x.config['ascension'] == 20, 'combat budget changed')
    jobs = [dict(mode='prefix', seed=state['seed'], state=state, candidate=candidate,
                 runtime=plan['runtime'], identity=x.identity, model=str(Path(plan['runtime']) / 'model.pt'),
                 output=str(root / 'branches' / f'{state["id"]}-{candidate}.json.gz'))
            for state in states for candidate in state['candidates']]
    E.require(64 <= len(jobs) <= plan['maximum_branches'], 'branch budget changed')
    E.write(root / 'jobs-private.json', jobs)
    deadline = time.monotonic() + plan['collection_timeout_seconds']
    E.run_branch_stage(x, root, jobs, 'E167_second_boss', deadline)
    results, outside = [], 0
    for job in jobs:
        row = E.checked_branch(x, job)
        outside += audit_parent_choices(x, row, job['state'], job['candidate'], parent)
        results.append(row)
    repeats = [dict(job, output=str(root / 'repeated' / Path(job['output']).name))
               for job, row in zip(jobs, results) if row['status'] == 'heart_win']
    reruns = x.H.run_jobs(root, repeats, x.config, 'E167_winner_continuations', deadline, worker_fn=E.branch_worker) if repeats else []
    for job, row in zip(repeats, reruns):
        original = E.read(root / 'branches' / Path(job['output']).name)
        E.require(x.P.qualified(row, job['state'], job['candidate'], x.identity['model_sha256'])
                  and row['status'] == original['status'] == 'heart_win'
                  and row['prefix'] == original['prefix']
                  and x.P.terminal_signature(row) == x.P.terminal_signature(original), 'winner continuation differs')
    E.require(len(reruns) == len(repeats), 'missing winner repeat')
    pairs = []
    for state in states:
        outcomes = {str(j['candidate']): int(r['status'] == 'heart_win')
                    for j, r in zip(jobs, results) if j['state']['id'] == state['id']}
        pairs.append(dict(seed=state['seed'], parent_candidate=state['chosen'], outcomes=outcomes,
                          option_names=state['option_names']))
    E.write(root / 'pairs-private.json', pairs)
    summary = summarize(pairs)
    report = dict(status='complete', experiment='E167', families=32, branches=len(jobs), **summary,
        eligible_for_scoped_learning=summary['rescuable_families'] >= plan['minimum_rescuable_families_for_learning'],
        nonintervention_nn_choices_verified=outside, fresh_winner_continuation_repeats=len(repeats),
        parent_controls_matched=32, zero_faults=True, optimizer_updates=0, production_adoption=False,
        limits='Conditional old Act2 boss-relic roots, not a natural policy win rate. Replay prefix and replan suffix; replan every winner twice. No new family or automatic expansion. A passing potential gate only admits a bounded scoped learning test.')
    E.write(root / 'report.json', report)
    paths = [Path(j['output']) for j in jobs+repeats] + [root / n for n in
        ('report.json', 'pairs-private.json', 'jobs-private.json', 'states-private.json', 'inventory-private.json', 'preparation.json')]
    E.write(root / 'completion.json', dict(status='complete', hashes={str(p.relative_to(root)): E.sha(p) for p in paths}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'collect', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'prepare': prepare, 'collect': collect, 'check': registered}[args.command](args.study.resolve())
