#!/usr/bin/env python3
"""Replay representative training games to locate early resource and decision failures."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time
import traceback

import heart_branch_pilot as P

H, R, A, S = P.H, P.R, P.A, P.S
REPO = Path(__file__).resolve().parent.parent


def public_summary(gc):
    deck = list(gc.deck)
    return {'act': gc.act, 'floor': gc.floor_num, 'hp': gc.cur_hp, 'max_hp': gc.max_hp,
        'gold': gc.gold, 'deck_size': len(deck), 'potion_count': gc.potion_count,
        'keys': [gc.red_key, gc.green_key, gc.blue_key],
        'cards': dict(Counter(c.id.name + ('+' if c.upgrade_count else '') for c in deck)),
        'nonstarter_attacks': sum(c.type == R.sts.CardType.ATTACK and not c.is_starter_strike_or_defend for c in deck),
        'relics': [str(r.id) for r in gc.relics]}


def audit(seed, path, expected_sha, config):
    if S.sha(path) != expected_sha:
        raise ValueError('source trajectory changed')
    run = H.read_json(path)
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
    battles, decisions = [], []
    for index, step in enumerate(run['prefix']):
        R.clock_input(gc, config)
        if gc.act <= 2:
            before = public_summary(gc)
            if step['kind'] == 'battle':
                flame_x, flame_y, _ = gc.burning_elite
                row = {**before, 'prefix_index': index, 'kind': 'battle',
                    'encounter': str(gc.encounter), 'room': str(gc.cur_room),
                    'burning_elite': gc.cur_room == R.sts.Room.ELITE and
                        (gc.cur_map_node_x, gc.cur_map_node_y) == (flame_x, flame_y),
                    'search_simulations': step['simulations'], 'turns': step['turns']}
            else:
                actions = list(R.sts.get_legal_game_actions(gc))
                _, descriptors, _ = A.build_choices(gc)
                chosen = [int(a.bits) for a in actions].index(step['action'])
                info = P.action_info(actions[chosen], descriptors[chosen])
                row = {**before, 'prefix_index': index, 'kind': 'outside',
                    'screen': str(gc.screen_state), 'event': gc.event_id_string,
                    'chosen': info, 'legal_count': len(actions)}
                if R.kind(descriptors[chosen]) == A.AK_MAP:
                    row.update(destination=str(gc.map_node_room(int(actions[chosen].idx1), gc.cur_map_node_y + 1)),
                        destination_burning=bool(descriptors[chosen][A.OFF_BURNING_ROOM]),
                        burning_reachable=bool(descriptors[chosen][A.OFF_BURNING_REACHABLE]))
        else:
            row = None
        R.replay_step(gc, step, config)
        if row is not None:
            row.update(hp_after=gc.cur_hp, outcome_after=R.terminal(gc))
            (battles if step['kind'] == 'battle' else decisions).append(row)
    R.clock_input(gc, config)
    P.verify_terminal(gc, run)
    return {'seed': seed, 'status': run['status'], 'act': run['act'], 'floor': run['floor'],
        'replay_verified': True, 'source_sha256': expected_sha, 'battles': battles, 'decisions': decisions}


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        result = audit(job['seed'], job['source'], job['source_sha256'], config)
    except Exception:
        result = {'seed': job['seed'], 'status': 'execution_error', 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def prepare(root, source):
    if root.exists(): raise ValueError('use a new audit directory')
    manifest = S.verify_files(source)
    seeds = H.read_json(source / 'seeds.json')['representative_train']
    index = {r['seed']: r for r in H.read_json(source / 'results-index.json')}
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
    shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
    shutil.copy2(__file__, root / 'run_audit.py')
    jobs = [{'mode': 'prefix', 'seed': seed, 'source': str(source / f'episodes/{seed}.json.gz'),
        'source_sha256': index[seed]['sha256'], 'output': str(root / f'audits/{seed}.json.gz')} for seed in seeds]
    for job in jobs:
        if S.sha(job['source']) != job['source_sha256']: raise ValueError('source changed')
    H.write_json(root / 'seeds.json', {'train_diagnostic': seeds})
    H.write_json(root / 'jobs.json', jobs)
    H.write_json(root / 'plan.json', {'experiment': 'E11', 'created_at': P.utc(),
        'question': 'Where do representative training games die before late policy takeover, and what public decisions/resources precede those failures?',
        'source': str(source), 'sample': 'All 1024 previously selected representative training seeds; no known-success enrichment.',
        'method': 'Read-only natural action replay. Record pre-battle resources and outside choices in acts one and two. No counterfactual outcome or causal claim from correlations alone.',
        'budget': '8 single-thread processes; 1800 seconds; original 150-second per-process guard.',
        'training_updates': 0, 'new_games': 0})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})


def run(root):
    S.verify_files(root)
    jobs, config = H.read_json(root / 'jobs.json'), H.read_json(root / 'config.json')
    results = H.run_jobs(root, jobs, config, 'early_training_replay', time.monotonic() + 1800, worker_fn=worker)
    errors = [r for r in results if not r.get('replay_verified')]
    if errors or len(results) != len(jobs):
        H.write_json(root / 'errors.json', errors)
        raise ValueError('incomplete audit or replay failure')
    deaths, fatal_battles, rests, risky = [], Counter(), Counter(), []
    for result in results:
        for d in result['decisions']:
            if d['chosen']['kind'] == 'AK_REST':
                rests[f'{d["act"]}:{d["chosen"].get("rest_option")}'] += 1
                if d['chosen'].get('rest_option') == 'upgrade' and d['hp'] / d['max_hp'] < .5:
                    risky.append({'seed': result['seed'], **d})
        if result['status'] == 'death' and result['act'] <= 2:
            fatal = next((b for b in reversed(result['battles']) if b['outcome_after'] == 'death'), None)
            if fatal:
                fatal_battles[f'{fatal["act"]}:{fatal["encounter"]}'] += 1
                prior = [d for d in result['decisions'] if d['prefix_index'] < fatal['prefix_index']]
                deaths.append({'seed': result['seed'], 'fatal': fatal, 'last_decisions': prior[-6:],
                    'last_rest': next((d for d in reversed(prior) if d['chosen']['kind'] == 'AK_REST'), None)})
    report = {'experiment': 'E11', 'status': 'complete', 'seeds': len(results), 'execution_faults': 0,
        'terminal_distribution': dict(Counter(f'{r["act"]}:{r["status"]}' for r in results)),
        'early_fatal_battle_count': len(deaths), 'fatal_encounters': dict(fatal_battles.most_common()),
        'fatal_rooms': dict(Counter(d['fatal']['room'] for d in deaths)),
        'fatal_burning_elites': sum(d['fatal']['burning_elite'] for d in deaths),
        'fatal_battle_start_hp': {bucket: sum(low <= d['fatal']['hp']/d['fatal']['max_hp'] < high for d in deaths)
            for bucket, low, high in [('under_25pct', 0, .25), ('25_to_50pct', .25, .5), ('50_to_75pct', .5, .75), ('75pct_plus', .75, 2)]},
        'fatal_potion_counts': dict(Counter(d['fatal']['potion_count'] for d in deaths)),
        'rest_choices': dict(rests), 'upgrade_below_half_hp_count': len(risky),
        'limits': 'Descriptive training-seed evidence; no inference that the preceding choice alone caused a death.'}
    H.write_json(root / 'early-deaths.json.gz', deaths)
    H.write_json(root / 'low-hp-upgrades.json.gz', risky)
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'result-index.json', [{'seed': job['seed'], 'path': job['output'], 'sha256': S.sha(job['output'])} for job in jobs])
    S.verify_files(root)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': 'complete', 'seeds': len(results)})
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--source', type=Path, default=REPO / 'runs/heart-training-set-evaluation-20260915-01')
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.root.resolve(), args.source.resolve())
    else: run(args.root.resolve())
