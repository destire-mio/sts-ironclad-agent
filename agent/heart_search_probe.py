#!/usr/bin/env python3
"""Compare search variants on identical natural winning and losing battles."""
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


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        if S.sha(job['source']) != job['source_sha256']:
            raise ValueError('source changed')
        run = H.read_json(job['source'])
        prefix, old = run['prefix'][:job['prefix_index']], run['prefix'][job['prefix_index']]
        gc = R.replay(job['seed'], prefix, config)
        if R.fingerprint(gc) != old['before'] or old['kind'] != 'battle':
            raise ValueError('entry state or RNG differs')
        before = R.fingerprint(gc)
        # The archived actions verify baseline rule transitions under this binary.
        original_end = R.replay(job['seed'], prefix + [old], config)
        control = {'hp': original_end.cur_hp, 'status': R.terminal(original_end),
            'potions': list(original_end.potions), 'fingerprint': R.fingerprint(original_end),
            'simulations': old['simulations'], 'outcome': old['outcome']}
        result = dict(R.sts.resolve_battle_recorded(gc, config['simulations'], config['boss_multiplier']))
        step = {'kind': 'battle', 'before': before, **result}
        R.clock_input(gc, config)
        restored = R.replay(job['seed'], prefix + [step], config)
        if R.fingerprint(gc) != R.fingerprint(restored):
            raise ValueError('new battle replay differs')
        if job['variant'] == 'original' and (step != old or R.fingerprint(gc) != control['fingerprint']):
            raise ValueError('rebuilt original search changed natural combat')
        output = {'seed': job['seed'], 'prefix_index': job['prefix_index'], 'valid': True,
            'stratum': job['stratum'], 'variant': job['variant'], 'baseline': control,
            'candidate': {'hp': gc.cur_hp, 'status': R.terminal(gc), 'potions': list(gc.potions),
                'fingerprint': R.fingerprint(gc), 'simulations': result['simulations'], 'outcome': result['outcome']},
            'prefix': prefix + [step], 'replay_verified': True}
    except Exception:
        output = {'seed': job['seed'], 'valid': False, 'error': traceback.format_exc()}
    H.write_json(job['output'], output)


def prepare(root, audit, build, variants=('original', 'minimal', 'normalized'), experiment='E14'):
    if root.exists(): raise ValueError('use a new experiment directory')
    S.verify_files(audit)
    build_report = H.read_json(build / 'build-report.json')
    for path, sha in build_report['inputs'].items():
        if S.sha(build / path) != sha: raise ValueError('build input changed')
    source = Path(H.read_json(audit / 'plan.json')['source'])
    manifest = S.verify_files(source)
    refs = {j['seed']: j for j in H.read_json(audit / 'jobs.json')}
    fatal = H.read_json(REPO / 'runs/heart-combat-probe-20260917-01/jobs.json')
    used = {r['seed'] for r in fatal}
    selections = [{'seed': j['seed'], 'prefix_index': j['prefix_index'], 'stratum': 'early_fatal'} for j in fatal]
    rng = random.Random(2026091704)
    pool = sorted(set(refs) - used)
    rng.shuffle(pool)
    for seed in pool:
        data = H.read_json(audit / f'audits/{seed}.json.gz')
        won = [b for b in data['battles'] if b['outcome_after'] != 'death']
        if not won: continue
        b = rng.choice(won)
        selections.append({'seed': seed, 'prefix_index': b['prefix_index'], 'stratum': 'early_survived'})
        if len(selections) == 256: break
    if len(selections) != 256: raise ValueError('insufficient controls')
    root.mkdir(parents=True)
    H.write_json(root / 'seeds.json', {'train_diagnostic': [s['seed'] for s in selections]})
    H.write_json(root / 'selections.json', selections)
    shutil.copy2(build / 'build-report.json', root / 'build-report.json')
    for name in ('search-minimal.patch', 'search-normalization.patch', 'search-rollout.patch'):
        if (build / name).exists(): shutil.copy2(build / name, root / name)
    for variant in variants:
        dest = root / variant
        dest.mkdir()
        for name in manifest['frozen_files']:
            if name.startswith(('source/', 'engine/')) or name == 'model.pt':
                path = dest / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, path)
        engine = build / variant / 'slaythespire.cpython-312-darwin.so'
        if S.sha(engine) != build_report['engines'][variant]: raise ValueError('engine changed')
        shutil.copy2(engine, dest / 'engine' / engine.name)
        shutil.copy2(P.__file__, dest / 'heart_branch_pilot.py')
        shutil.copy2(__file__, dest / 'run_search_probe.py')
        config = H.read_json(source / 'config.json')
        config['workers'] = 2
        config['experiment'] = experiment
        H.write_json(dest / 'config.json', config)
        jobs = [{'mode': 'prefix', **s, 'variant': variant, 'source': refs[s['seed']]['source'],
            'source_sha256': refs[s['seed']]['source_sha256'],
            'output': str(dest / f'episodes/{s["seed"]}.json.gz')} for s in selections]
        H.write_json(dest / 'jobs.json', jobs)
        H.write_json(dest / 'manifest.json', {'frozen_files': {str(p.relative_to(dest)): S.sha(p)
            for p in dest.rglob('*') if p.is_file()}})
    H.write_json(root / 'plan.json', {'experiment': experiment, 'created_at': P.utc(),
        'question': 'Does the frozen search variant improve battle quality at the original budget?',
        'sample': '128 E12 early fatalities plus 128 naturally survived early battles from other E11 training roots, one per root; survival controls selected with fixed RNG 2026091704.',
        'arms': {'original': 'Unchanged search recompiled and relinked against the same archived rule objects; must reproduce original search.',
            'minimal': 'Initialize best value with lowest finite double and handle zero score range; otherwise retain old UCB.',
            'normalized': 'Minimal correction plus affine-invariant mean UCB and explicit unvisited-edge exploration.',
            'rollout': 'Normalized search plus END_TURN relative sampling weight 0.1 while any card action is legal in random rollouts. Full legal action coverage and tree expansion unchanged; no extra simulations.'},
        'executed_arms': list(variants),
        'comparison': 'For E17, use the identical E14 selected states and its frozen normalized results as the direct control; verify selection equality before analysis. No sweep of the 0.1 weight.',
        'budget': 'All 8000 MCTS per search, boss multiplier 3; two workers per arm, sequential arms; 1800 seconds per arm.',
        'controls': 'Same natural entry state/RNG; frozen old action replay and new action replay. Report fatal rescues AND previously survived battles lost. Game-rule object files identical.',
        'decision': 'Battle gains justify a new whole-run development experiment, not promotion. More HP with fewer potions is a tradeoff. No improvement rejects these numeric changes as an established performance remedy.',
        'limits': 'Failure-enriched training-state diagnostic, not whole-run or unseen performance; normalized arm also changes UCB scaling, so separate its effects from the minimal correction.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})


def run(root):
    S.verify_files(root)
    config, jobs = H.read_json(root / 'config.json'), H.read_json(root / 'jobs.json')
    rows = H.run_jobs(root, jobs, config, 'search_numerical_probe', time.monotonic() + 1800, worker_fn=worker)
    bad = [r for r in rows if not r.get('valid')]
    if bad or len(rows) != len(jobs):
        H.write_json(root / 'errors.json', bad)
        raise ValueError('invalid or missing search probe')
    def stats(selected):
        return {'battles': len(selected),
            'baseline_survived': sum(r['baseline']['status'] != 'death' for r in selected),
            'candidate_survived': sum(r['candidate']['status'] != 'death' for r in selected),
            'rescued': sum(r['baseline']['status'] == 'death' and r['candidate']['status'] != 'death' for r in selected),
            'lost': sum(r['baseline']['status'] != 'death' and r['candidate']['status'] == 'death' for r in selected),
            'same_final_state': sum(r['baseline']['fingerprint'] == r['candidate']['fingerprint'] for r in selected),
            'baseline_total_simulations': sum(r['baseline']['simulations'] for r in selected),
            'candidate_total_simulations': sum(r['candidate']['simulations'] for r in selected)}
    report = {'experiment': config.get('experiment', 'E14'), 'status': 'complete', 'variant': jobs[0]['variant'],
        'execution_faults': 0, 'overall': stats(rows), 'strata': {s: stats([r for r in rows if r['stratum'] == s])
            for s in sorted({j['stratum'] for j in jobs})}}
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'result-index.json', [{'seed': j['seed'], 'prefix_index': j['prefix_index'],
        'path': str(Path(j['output']).relative_to(root)), 'sha256': S.sha(j['output'])} for j in jobs])
    S.verify_files(root)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': 'complete'})
    print(report, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare', 'run'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--audit', type=Path, default=REPO / 'runs/heart-early-diagnosis-20260917-01')
    p.add_argument('--build', type=Path, default=REPO / 'runs/heart-search-numerics-build-20260917-03')
    p.add_argument('--variants', nargs='+', default=['original', 'minimal', 'normalized'])
    p.add_argument('--experiment', default='E14')
    a = p.parse_args()
    if a.command == 'prepare': prepare(a.root.resolve(), a.audit.resolve(), a.build.resolve(), a.variants, a.experiment)
    else: run(a.root.resolve())
