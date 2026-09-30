#!/usr/bin/env python3
"""One-battle budget intervention at naturally reached early fatal states."""
import argparse
from collections import Counter
from pathlib import Path
import random
import shutil
import time
import traceback

import heart_branch_pilot as P

H, R, S = P.H, P.R, P.S
REPO = Path(__file__).resolve().parent.parent


def replay_potions(gc, step):
    bc = R.sts.BattleContext()
    bc.init(gc)
    initial = list(bc.potions)
    actions = []
    for bits in step['actions']:
        action = R.sts.SearchAction.from_bits(bits & 0xffffffff)
        if not action.is_valid(bc):
            raise ValueError('illegal battle action')
        if 'POTION' in str(action.action_type):
            actions.append({'turn': bc.turn, 'description': action.desc(bc),
                'source': action.source_idx, 'target': action.target_idx})
        action.execute(bc)
    if int(bc.outcome) != step['outcome']:
        raise ValueError('battle replay outcome differs')
    return {'before': initial, 'after': list(bc.potions), 'actions': actions}


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        if S.sha(job['source']) != job['source_sha256']:
            raise ValueError('source changed')
        run = H.read_json(job['source'])
        index = job['prefix_index']
        before_prefix, original = run['prefix'][:index], run['prefix'][index]
        net = H.load_scorer(H.torch.load(job['model'], map_location='cpu', weights_only=True))
        outputs = []
        for budget in (8000, 32000):
            gc = R.replay(job['seed'], before_prefix, config)
            if R.fingerprint(gc) != original['before'] or original['kind'] != 'battle':
                raise ValueError('fatal battle entry differs')
            potion_audit = replay_potions(gc, original)
            battle_result = dict(R.sts.resolve_battle_recorded(gc, budget, config['boss_multiplier']))
            step = {'kind': 'battle', 'before': original['before'], **battle_result}
            state_after = {'status': R.terminal(gc), 'hp': gc.cur_hp, 'potions': list(gc.potions)}
            if budget == 8000 and step != original:
                raise ValueError('original budget does not reproduce fatal battle')
            remaining = config['max_steps'] - index - 1
            suffix = R.rollout(job['seed'], {**config, 'max_steps': remaining}, gc=gc,
                net=net, record=True, record_samples=False)
            R.clock_input(gc, config)
            suffix.update(prefix=before_prefix + [step] + suffix['prefix'],
                terminal_fingerprint=R.fingerprint(gc), battle_budget=budget,
                intervened_battle=state_after, original_potion_audit=potion_audit)
            if R.target(suffix['status']) is None:
                raise ValueError('invalid continuation: ' + str(suffix.get('error')))
            P.verify_terminal(R.replay(job['seed'], suffix['prefix'], config), suffix)
            suffix['replay_verified'] = True
            if budget == 8000 and (suffix['prefix'] != run['prefix'] or
                    P.terminal_signature(suffix) != P.terminal_signature(run)):
                raise ValueError('original continuation differs')
            outputs.append(suffix)
        result = {'seed': job['seed'], 'prefix_index': index, 'valid': True,
            'fatal': job['fatal'], 'arms': outputs}
    except Exception:
        result = {'seed': job['seed'], 'valid': False, 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def prepare(root, audit_root):
    if root.exists(): raise ValueError('use a new experiment directory')
    S.verify_files(audit_root)
    source = Path(H.read_json(audit_root / 'plan.json')['source'])
    manifest = S.verify_files(source)
    deaths = H.read_json(audit_root / 'early-deaths.json.gz')
    selected = random.Random(2026091702).sample(sorted(deaths, key=lambda d: d['seed']), 128)
    index = {r['seed']: r for r in H.read_json(source / 'results-index.json')}
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
    shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
    shutil.copy2(__file__, root / 'run_probe.py')
    jobs = [{'mode': 'prefix', 'seed': d['seed'], 'prefix_index': d['fatal']['prefix_index'],
        'fatal': d['fatal'], 'source': str(source / f'episodes/{d["seed"]}.json.gz'),
        'source_sha256': index[d['seed']]['sha256'], 'model': str(root / 'model.pt'),
        'output': str(root / f'episodes/{d["seed"]}.json.gz')} for d in selected]
    H.write_json(root / 'jobs.json', jobs)
    H.write_json(root / 'seeds.json', {'train_diagnostic': [d['seed'] for d in selected]})
    H.write_json(root / 'plan.json', {'experiment': 'E12', 'created_at': P.utc(),
        'hypothesis': 'Early fatal states may be recoverable by stronger combat alone; distinguish combat budget from outside decisions.',
        'selection': 'Fixed RNG 2026091702, uniform 128 of 875 early fatal battle states, one per training seed. Not selected on potion, health or future intervention outcome.',
        'intervention': 'At the original fatal battle only, compare 8000 versus 32000 MCTS simulations per search, boss multiplier 3. All earlier actions replayed; all later combat reverts to 8000 and outside choices use original network.',
        'controls': '8000 must reproduce original actions, state, RNG and terminal. Both arms naturally replayed. Replay original potion use and discard actions.',
        'budget': '8 workers, 150 seconds per job, 1800 seconds total. No training or global combat change.',
        'decision': 'Frequent rescue identifies current combat search as a material early limit. Few rescues fail to support this specific budget intervention; they do not establish impossibility or clear the combat implementation.',
        'limits': 'Failure-enriched conditional diagnostic, not a whole-run win rate or unseen evaluation.',
        'audit_report_sha256': S.sha(audit_root / 'report.json')})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})


def run(root):
    S.verify_files(root)
    jobs, config = H.read_json(root / 'jobs.json'), H.read_json(root / 'config.json')
    results = H.run_jobs(root, jobs, config, 'fatal_battle_budget_probe', time.monotonic() + 1800, worker_fn=worker)
    bad = [r for r in results if not r.get('valid')]
    if bad or len(results) != len(jobs):
        H.write_json(root / 'errors.json', bad)
        raise ValueError('invalid or missing probe results')
    rescued = [r for r in results if r['arms'][1]['intervened_battle']['status'] != 'death']
    wins = [r['seed'] for r in results if r['arms'][1]['status'] == 'heart_win']
    report = {'experiment': 'E12', 'status': 'complete', 'seeds': len(results),
        'original_controls': len(results), 'execution_faults': 0, 'battle_rescues': len(rescued),
        'rescue_encounters': dict(Counter(r['fatal']['encounter'] for r in rescued)),
        'original_encounters': dict(Counter(r['fatal']['encounter'] for r in results)),
        'heart_rescues': wins, 'new_terminals': dict(Counter(f'{r["arms"][1]["act"]}:{r["arms"][1]["status"]}' for r in results)),
        'original_potion_actions': dict(Counter(a['description'] for r in results
            for a in r['arms'][0]['original_potion_audit']['actions'])),
        'limits': 'Single-battle intervention on early failures from training seeds; conditional diagnostic.'}
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'result-index.json', [{'seed': j['seed'], 'path': j['output'], 'sha256': S.sha(j['output'])} for j in jobs])
    S.verify_files(root)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': 'complete'})
    print(report, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare', 'run'))
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--audit', type=Path, default=REPO / 'runs/heart-early-diagnosis-20260917-01')
    a = p.parse_args()
    if a.command == 'prepare': prepare(a.root.resolve(), a.audit.resolve())
    else: run(a.root.resolve())
