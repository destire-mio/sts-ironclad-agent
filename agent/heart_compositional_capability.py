"""Bounded, hindsight teacher diagnostic; never a deployable public policy.

Compare single changes against sequential changes at the same rollout budget.
Frozen combat and parent outside policy finish each genuinely reached branch.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time
import traceback

import heart_trajectory_value_data as D

E = D.E
RECIPE = dict(families=16, shared=16, extra=16, max_changes=4, workers=8,
              seconds=5400, per_suffix_seconds=300, minimum_wins=8, minimum_gain=4)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def put(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(temporary, 'wt') as stream:
        json.dump(value, stream, separators=(',', ':'))
    temporary.replace(path)


def strategic_options(A, kinds, parent):
    """Change a decision, not the ordering of administrative reward claims."""
    groups = ({A.AK_MAP}, {A.AK_REST}, {A.AK_EVENT},
              {A.AK_REWARD_CARD, A.AK_REWARD_SKIP, A.AK_REWARD_SINGING_BOWL},
              {A.AK_SHOP_CARD, A.AK_SHOP_RELIC, A.AK_SHOP_POTION, A.AK_SHOP_REMOVE, A.AK_SHOP_LEAVE},
              {A.AK_BOSS_RELIC, A.AK_BOSS_SKIP}, {A.AK_CARD_SELECT, A.AK_CARD_SELECT_CANCEL})
    group = next((group for group in groups if kinds[parent] in group), None)
    return [i for i, kind in enumerate(kinds) if group is not None and kind in group and i != parent]


def mutations(x, run, prior_changes):
    """Regenerate legal roots by natural replay; full prefix identity is used."""
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    options = []; prefix_hash = hashlib.sha256(); changes = []
    for index, step in enumerate(run['prefix']):
        x.R.clock_input(gc, x.config)
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc)); _, ds, _ = x.A.build_choices(gc)
            bits = [int(a.bits) for a in actions]
            chosen = bits.index(step['action']); kinds = [x.R.kind(d) for d in ds]
            # A mutation after earlier changes carries those changes forward.
            inherited = [c for c in prior_changes if c['index'] < index]
            if len(inherited) < RECIPE['max_changes']:
                for position in strategic_options(x.A, kinds, chosen):
                    change = dict(index=index, before=step['before'], action=bits[position],
                                  act=int(gc.act), floor=int(gc.floor_num), kind=kinds[position])
                    key = digest([prefix_hash.hexdigest(), step['before'], bits[position]])
                    options.append(dict(key=key, index=index, action=bits[position],
                                        act=int(gc.act), changes=inherited + [change]))
        x.R.replay_step(gc, step, x.config)
        prefix_hash.update(json.dumps(step, sort_keys=True, separators=(',', ':')).encode())
    x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run)
    return options


def pick_mutation(options, used, seed, attempt):
    remaining = [o for o in options if o['key'] not in used]
    if not remaining:
        return None
    # Balance opportunities across reachable acts without using branch outcomes.
    acts = sorted({o['act'] for o in remaining}); act = acts[attempt % len(acts)]
    return min((o for o in remaining if o['act'] == act),
               key=lambda o: digest(['P200-action', seed, attempt, o['key']]))


def progress(run):
    return (int(run['status'] == 'heart_win'), int(run['act']), int(run['floor']))


def select_source(archive, seed, attempt):
    eligible = [r for r in archive if len(r['changes']) < RECIPE['max_changes']]
    if attempt % 4 == 3:
        return min(eligible, key=lambda r: digest(['P200-explore', seed, attempt, r['id']]))
    # Preserve different intervention sequences rather than a single incumbent.
    ranked = sorted(eligible, key=lambda r: (progress(r['run']), digest(r['changes'])), reverse=True)
    return ranked[(attempt % 4) % min(3, len(ranked))]


def check_route(x, run):
    E.require(not run.get('error') and run['status'] in ('heart_win', 'death', 'act3_without_heart'),
              'fault/truncation is not a terminal reward')
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    bosses = []; fourth = []
    for step in run['prefix']:
        x.R.clock_input(gc, x.config)
        if step['kind'] == 'battle':
            if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS:
                bosses.append(gc.encounter.name)
            if gc.act == 4:
                E.require(gc.red_key and gc.green_key and gc.blue_key, 'missing keys')
                fourth.append(gc.encounter.name)
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run)
    if run['status'] == 'heart_win':
        E.require(len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART'],
                  'incomplete A20 Heart chain')
    return dict(state_rng_terminal=True, act3_bosses=bosses, act4=fourth)


def continue_branch(x, model, source, proposal):
    seed = source['seed']; prefix = source['prefix'][:proposal['index']]
    gc = x.R.replay(seed, prefix, x.config)
    E.require(x.R.fingerprint(gc) == source['prefix'][proposal['index']]['before'], 'wrong root')
    action = x.R.sts.GameAction(proposal['action'] & 0xffffffff)
    E.require(action.is_valid(gc), 'invalid changed action')
    step = dict(kind='outside', before=x.R.fingerprint(gc), action=proposal['action'])
    action.execute(gc)
    config = dict(x.config, max_steps=x.config['max_steps'] - len(prefix) - 1,
                  episode_seconds=RECIPE['per_suffix_seconds'])
    run = x.R.rollout(seed, config, gc=gc, net=model, record=True, record_samples=False)
    x.R.clock_input(gc, x.config)
    run.update(prefix=prefix + [step] + run['prefix'], terminal_fingerprint=x.R.fingerprint(gc),
               engine_sha256=x.identity['engine_sha256'], checkpoint_sha256=x.identity['model_sha256'])
    run['audit'] = check_route(x, run)
    return run


class FixedChanges:
    """Replay a teacher's actions for verification, never for public evaluation."""
    def __init__(self, x, parent, changes):
        self.x = x; self.parent = parent; self.changes = changes; self.applied = []

    def choose(self, gc, observation, actions, descriptors):
        before = self.x.R.fingerprint(gc)
        matching = [c for c in self.changes if c['before'] == before]
        if matching:
            E.require(len(matching) == 1, 'ambiguous forced state')
            change = matching[0]; self.applied.append(change)
            return [int(a.bits) for a in actions].index(change['action'])
        return self.parent.choose(gc, observation, actions, descriptors)


def replan(x, model, seed, record):
    policy = FixedChanges(x, model, record['changes'])
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
    run = x.R.rollout(seed, x.config, gc=gc, net=policy, record=True, record_samples=False)
    x.R.clock_input(gc, x.config); run['terminal_fingerprint'] = x.R.fingerprint(gc)
    check_route(x, run)
    E.require(policy.applied == record['changes'], 'planned intervention was not reached')
    E.require(run['prefix'] == record['run']['prefix'] and
              x.P.terminal_signature(run) == x.P.terminal_signature(record['run']), 'fresh planning differs')
    return run


def family(job):
    root = Path(job['root']); folder = root / 'families' / str(job['seed']); folder.mkdir(parents=True)
    started = time.monotonic(); candidate_count = 0
    try:
        plan = E.read(root / 'protocol.json')
        E.require(E.sha(__file__) == plan['runner_sha256'], 'registered runner changed')
        x = D.runtime(plan['runtime']); model = E.parent_model(x)
        reference = job['reference']; E.require(E.sha(reference['path']) == reference['sha256'], 'source changed')
        old = E.read(reference['path'])
        E.require(old['seed'] == job['seed'] and old['engine_sha256'] == x.identity['engine_sha256']
                  and old['checkpoint_sha256'] == x.identity['model_sha256'], 'source runtime mismatch')
        check_route(x, old)
        baseline = dict(id='parent', changes=[], run=old)
        if job['control']:
            put(folder / 'parent-control.json.gz', replan(x, model, job['seed'], baseline))
        options = {'parent': mutations(x, old, [])}; archive = [baseline]; used = set(); records = {}
        groups = dict(shared=[], single=[], composite=[])

        def evaluate(stage, at, source):
            nonlocal candidate_count
            E.require(time.monotonic() - job['started_monotonic'] < RECIPE['seconds'], 'study time budget reached')
            if source['id'] not in options:
                options[source['id']] = mutations(x, source['run'], source['changes'])
            proposal = pick_mutation(options[source['id']], used, job['seed'], at)
            if proposal is None:
                return None
            used.add(proposal['key']); candidate_count += 1
            run = continue_branch(x, model, source['run'], proposal)
            record = dict(id=f'{stage}-{at:02d}', parent_id=source['id'], changes=proposal['changes'],
                          proposal_key=proposal['key'], run=run)
            put(folder / (record['id'] + '.json.gz'), record)
            records[record['id']] = record; groups[stage].append(record['id'])
            put(folder / 'status.json', dict(status='running', stage=stage, candidates=candidate_count,
                heart_candidates=sum(r['run']['status'] == 'heart_win' for r in records.values()),
                seconds=time.monotonic() - started))
            return record

        if old['status'] != 'heart_win':
            for at in range(RECIPE['shared']):
                record = evaluate('shared', at, baseline)
                if record is not None: archive.append(record)
            shared_used = used.copy()
            # Counterbalanced order across families; both arms share only prefix facts.
            for stage in (['single', 'composite'] if job['position'] % 2 == 0 else ['composite', 'single']):
                used = shared_used.copy()
                for at in range(RECIPE['extra']):
                    source = baseline if stage == 'single' else select_source(archive, job['seed'], at)
                    record = evaluate(stage, RECIPE['shared'] + at, source)
                    if stage == 'composite' and record is not None: archive.append(record)
        best = {}
        for stage in ('single', 'composite'):
            candidates = [baseline] + [records[k] for k in groups['shared'] + groups[stage]]
            best[stage] = min(candidates, key=lambda r: (-int(r['run']['status'] == 'heart_win'),
                                                       len(r['changes']), r['id']))
        replanned = {}
        for record in best.values():
            if record['run']['status'] == 'heart_win' and record['id'] not in replanned:
                replanned[record['id']] = replan(x, model, job['seed'], record)
                put(folder / ('replan-' + record['id'] + '.json.gz'), replanned[record['id']])
        result = dict(status='complete', seed=job['seed'], position=job['position'],
            parent_win=old['status'] == 'heart_win', groups=groups, candidates=candidate_count,
            selected={stage: dict(id=r['id'], win=r['run']['status'] == 'heart_win', changes=r['changes'])
                      for stage, r in best.items()}, winner_replans=len(replanned),
            fresh_control=job['control'], seconds=time.monotonic() - started,
            simulations=sum(r['run']['simulations'] for r in records.values()),
            limits='Hindsight search feasibility on historical training families; not public-policy win rate.')
    except Exception:
        result = dict(status='fault', seed=job['seed'], candidates=candidate_count, error=traceback.format_exc())
    put(folder / 'result.json', result)
    return result


def prepare(root, source):
    E.require(not root.exists(), 'new study directory required')
    root.mkdir(parents=True)
    references = E.read(source / 'fit-references.json')
    excluded = set(E.read(source.parent / 'heart-e191-whole-policy-gradient-20260924-01/roles-private.json')['evaluation'])
    eligible = [r for r in references if r['seed'] not in excluded]
    selected = sorted(eligible, key=lambda r: hashlib.sha256(f'P200-family:{r["seed"]}'.encode()).hexdigest())[:RECIPE['families']]
    E.require(len(selected) == RECIPE['families'] and len({r['seed'] for r in selected}) == len(selected), 'family split failed')
    plan = dict(experiment='P200', recipe=RECIPE, runtime=str((source / 'runtime').resolve()),
                source=str(source.resolve()), runner_sha256=E.sha(__file__),
                reference_index_sha256=E.sha(source / 'fit-references.json'),
                selection='SHA256 P200-family:seed ascending; source fit only minus E191 evaluation; no outcome filter',
                total_new_plans_maximum=808, preflight_maximum=6, public_policy_evaluation=False,
                limits='Positive results establish a bounded teacher lower bound; negatives do not establish combat or global optimality ceiling.')
    put(root / 'protocol.json', plan); put(root / 'references.json', selected)
    put(root / 'status.json', dict(status='prepared', new_games=0))
    print(json.dumps(dict(root=str(root), families=len(selected), total_new_plans_maximum=808)), flush=True)


def preflight(root):
    plan = E.read(root / 'protocol.json')
    E.require(E.sha(__file__) == plan['runner_sha256'], 'runner changed')
    x = D.runtime(plan['runtime']); model = E.parent_model(x)
    reference = E.read(root / 'references.json')[0]
    E.require(E.sha(reference['path']) == reference['sha256'], 'source changed')
    old = E.read(reference['path']); base = dict(id='parent', changes=[], run=old)
    folder = root / 'preflight'; folder.mkdir()
    put(folder / 'control.json.gz', replan(x, model, old['seed'], base))
    options = mutations(x, old, [])
    cards = [o for o in options if o['changes'][-1]['kind'] == x.A.AK_REWARD_CARD]
    E.require(cards, 'preselected control lacks a legal card intervention')
    first = min(cards, key=lambda o: (o['index'], o['action']))
    one = dict(id='one', changes=first['changes'], run=continue_branch(x, model, old, first))
    put(folder / 'one.json.gz', one)
    put(folder / 'one-replanned.json.gz', replan(x, model, old['seed'], one))
    subsequent = [o for o in mutations(x, one['run'], one['changes']) if o['index'] > first['index']]
    E.require(subsequent, 'no later strategic decision in fixed preflight')
    second = min(subsequent, key=lambda o: (o['index'], o['action']))
    E.require(len(second['changes']) == 2 and second['changes'][0] == first['changes'][0], 'composition lost earlier intervention')
    two = dict(id='two', changes=second['changes'], run=continue_branch(x, model, one['run'], second))
    put(folder / 'two.json.gz', two)
    put(folder / 'two-replanned.json.gz', replan(x, model, old['seed'], two))
    report = dict(status='passed', seed=old['seed'], new_plans=5, unchanged_control=True,
                  first_intervention_replanned=True, composed_interventions_replanned=True,
                  recorded_states_rng_actions_terminal_match=True, runner_sha256=E.sha(__file__))
    put(root / 'preflight.json', report); print(json.dumps(report), flush=True)


def run(root):
    plan = E.read(root / 'protocol.json'); E.require(plan['recipe'] == RECIPE and E.sha(__file__) == plan['runner_sha256'], 'plan changed')
    checks = E.read(root / 'preflight.json')
    E.require(checks['status'] == 'passed' and checks['runner_sha256'] == E.sha(__file__), 'native preflight required')
    references = E.read(root / 'references.json'); started = time.monotonic()
    jobs = [dict(root=str(root), seed=r['seed'], reference=r, position=i, control=i < 2, started_monotonic=started)
            for i, r in enumerate(references)]
    put(root / 'launch.json', dict(pid=os.getpid(), started=time.time(), runner_sha256=E.sha(__file__)))
    results = []
    with ProcessPoolExecutor(max_workers=RECIPE['workers'], mp_context=multiprocessing.get_context('spawn')) as executor:
        futures = [executor.submit(family, job) for job in jobs]
        for future in as_completed(futures):
            result = future.result(); results.append(result)
            put(root / 'status.json', dict(status='running', completed=len(results), assigned=len(jobs),
                faults=sum(r['status'] != 'complete' for r in results), seconds=time.monotonic() - started))
            print(json.dumps({k: result[k] for k in ('status', 'seed', 'candidates')}), flush=True)
    valid = [r for r in results if r['status'] == 'complete']; single = sum(r['selected']['single']['win'] for r in valid)
    composite = sum(r['selected']['composite']['win'] for r in valid)
    complete = len(valid) == RECIPE['families']
    result = dict(status='complete' if complete else 'incomplete_faults', assigned=len(jobs), valid=len(valid),
        faults=len(results)-len(valid), parent_wins=sum(r['parent_win'] for r in valid),
        single_teacher_wins=single, composite_teacher_wins=composite,
        paired_composite_only=sum(r['selected']['composite']['win'] and not r['selected']['single']['win'] for r in valid),
        paired_single_only=sum(r['selected']['single']['win'] and not r['selected']['composite']['win'] for r in valid),
        capability_gate_passed=complete and composite >= RECIPE['minimum_wins'] and composite-single >= RECIPE['minimum_gain'],
        new_candidates=sum(r['candidates'] for r in results), seconds=time.monotonic()-started,
        public_policy_wins=None, unseen_acceptance_games=0,
        families=sorted(results, key=lambda r: r.get('position', 999)))
    put(root / 'result.json', result); put(root / 'status.json', dict(status=result['status'], completed=len(results), faults=result['faults']))
    print(json.dumps({k:v for k,v in result.items() if k != 'families'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('command', choices=('prepare', 'preflight', 'run'))
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.root.resolve(), args.source.resolve())
    elif args.command == 'preflight': preflight(args.root.resolve())
    else: run(args.root.resolve())
