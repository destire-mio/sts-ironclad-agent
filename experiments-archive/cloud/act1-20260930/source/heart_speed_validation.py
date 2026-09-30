#!/usr/bin/env python3
"""Exact whole-run controls and isolated paired timing for the E30 optimization."""
import argparse
from collections import Counter
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import time

import heart_combat_development as C

P, H, R, S = C.P, C.H, C.R, C.S
REPO = Path(__file__).resolve().parent.parent
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'


def prepare(root, probe=None, experiment='E30', control_probe=None):
    if root.exists():
        raise ValueError('use a new validation directory')
    source = REPO / 'runs/heart-order-development-20260917-01'
    probe = probe or REPO / 'runs/heart-speed-probe-20260917-01'
    manifest = S.verify_files(source)
    rng = random.Random(2026091712)
    pools = {s: [] for s in ('act1_death', 'act2_death', 'late_death', 'heart_win')}
    index = H.read_json(source / 'result-index.json')
    for entry in index:
        path = source / f'episodes/{entry["seed"]}.json.gz'
        assert S.sha(path) == entry['sha256']
        row = H.read_json(path)
        if row['status'] == 'heart_win':
            stratum = 'heart_win'
        elif row['status'] == 'death':
            stratum = 'act1_death' if row['act'] == 1 else 'act2_death' if row['act'] == 2 else 'late_death'
        else:
            continue
        pools[stratum].append({**entry, 'stratum': stratum, 'path': str(path)})
    references = [row for rows in pools.values() for row in rng.sample(sorted(rows, key=lambda r: r['seed']), 16)]
    selected = H.read_json(probe / 'selections.json')
    panel = [row for stratum in ('early_fatal', 'late_fatal', 'early_survived', 'late_survived')
             for row in rng.sample([r for r in selected if r['stratum'] == stratum], 4)]
    orders = [['baseline', 'candidate'], ['candidate', 'baseline']] * 4
    random.Random(2026091713).shuffle(orders)
    root.mkdir(parents=True)
    origins = [(None, source), ('baseline', source), ('candidate', probe / 'fast')]
    if control_probe is not None:
        origins.append(('rebuilt_control', control_probe / 'rebuilt'))
    for arm, origin in origins:
        dest = root if arm is None else root / arm
        dest.mkdir(parents=True, exist_ok=True)
        origin_manifest = S.verify_files(origin)
        for name in origin_manifest['frozen_files']:
            if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
                target = dest / name
                target.parent.mkdir(exist_ok=True, parents=True)
                shutil.copy2(origin / name, target)
        for original, name in ((P.__file__, 'heart_branch_pilot.py'), (C.__file__, 'heart_combat_development.py'), (__file__, 'run_speed_validation.py')):
            shutil.copy2(original, dest / name)
        config = H.read_json(source / 'config.json')
        config['workers'] = 8
        H.write_json(dest / 'config.json', config)
        H.write_json(dest / 'references.json', references)
        H.write_json(dest / 'timing-panel.json', panel)
        H.write_json(dest / 'identity.json', {'arm': arm, 'engine_sha256': S.sha(dest / ENGINE),
            'model_sha256': S.sha(dest / 'model.pt')})
        if arm:
            H.write_json(dest / 'manifest.json', {'frozen_files': {str(p.relative_to(dest)): S.sha(p)
                for p in dest.rglob('*') if p.is_file()}})
    H.write_json(root / 'seeds.json', {'train_equivalence': [r['seed'] for r in references],
        'training_timing_states': [r['seed'] for r in panel]})
    plan = {'experiment': experiment, 'created_at': P.utc(), 'source': str(source),
        'source_report_sha256': S.sha(source / 'report.json'), 'probe': str(probe),
        'probe_plan_sha256': S.sha(probe / 'plan.json'),
        'whole_controls': '64 natural openings, 16 each act-one death, act-two death, later death, Heart win from E23; RNG 2026091712. Enriched equivalence panel, no success-rate estimator.',
        'benchmark': '16 fixed natural battle states, four per E26 stratum; eight paired rounds. One excluded warmup battle per arm/round. Sequential child processes with one native thread; no concurrent experiment jobs. Timer encloses resolve_battle_recorded only, excluding imports, restoration and verification. Every timed action/state/RNG must match E23.',
        'round_orders': orders, 'bootstrap_round_resamples': 10000, 'bootstrap_seed': 2026091714,
        'gate': {'required_battle_matches': 256, 'required_whole_matches': 64,
            'minimum_median_paired_time_reduction': .05, 'bootstrap_lower_bound_strictly_above': 0},
        'limits': 'Fixed-work simulator search benchmark, not whole training throughput, a new Heart win-rate estimate or original Java parity. No fresh acceptance seeds.'}
    if control_probe is not None:
        plan['control_probe'] = str(control_probe)
        plan['control_probe_plan_sha256'] = S.sha(control_probe / 'plan.json')
        plan['additional_source_control'] = 'The rebuilt O0 binding runtime must match all 256 state controls and the same 64 natural whole traces before timing the accepted original versus the O2 candidate.'
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})
    print({'prepared': str(root), 'whole_controls': len(references), 'timing_states': len(panel)}, flush=True)


def whole(root):
    S.verify_files(root)
    identity, config = H.read_json(root / 'identity.json'), H.read_json(root / 'config.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    references = H.read_json(root / 'references.json')
    jobs = [{'mode': 'prefix', 'seed': r['seed'], 'model': str(root / 'model.pt'), **identity,
             'output': str(root / f'episodes/{r["seed"]}.json.gz')} for r in references]
    rows = H.run_jobs(root, jobs, config, 'whole_trace_equivalence', time.monotonic() + 1800, worker_fn=C.worker)
    checks = []
    for ref, row, job in zip(references, rows, jobs):
        assert S.sha(ref['path']) == ref['sha256']
        old = H.read_json(ref['path'])
        assert row.get('replay_verified') and row.get('terminal_state_verified')
        assert row['engine_sha256'] == identity['engine_sha256']
        assert row['checkpoint_sha256'] == old['checkpoint_sha256'] == identity['model_sha256']
        assert row['prefix'] == old['prefix'] and P.terminal_signature(row) == P.terminal_signature(old)
        assert row['simulations'] == old['simulations']
        checks.append({'seed': row['seed'], 'stratum': ref['stratum'], 'matched': True,
                       'path': job['output'], 'sha256': S.sha(job['output'])})
    assert len(checks) == len(references) == 64
    H.write_json(root / 'whole-verification.json', {'status': 'complete', 'matched': len(checks),
        'strata': dict(Counter(c['stratum'] for c in checks)), 'results': checks})
    print({'whole_matches': len(checks)}, flush=True)


def timing(root, round_index):
    S.verify_files(root)
    identity = H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    config = H.read_json(root / 'config.json')
    panel = H.read_json(root / 'timing-panel.json')
    plan = H.read_json(root.parent / 'plan.json')
    source = Path(plan['source'])
    original_index = {r['seed']: r['sha256'] for r in H.read_json(source / 'result-index.json')}
    records = []
    H.torch.set_num_threads(1)
    for index, selection in enumerate([panel[0]] + panel):
        path = source / f'episodes/{selection["seed"]}.json.gz'
        assert S.sha(path) == original_index[selection['seed']]
        original = H.read_json(path)
        prefix = original['prefix'][:selection['prefix_index']]
        old = original['prefix'][selection['prefix_index']]
        gc = R.replay(selection['seed'], prefix, config)
        assert R.fingerprint(gc) == old['before']
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        result = dict(R.sts.resolve_battle_recorded(gc, config['simulations'], config['boss_multiplier']))
        cpu_ns, wall_ns = time.process_time_ns() - cpu, time.perf_counter_ns() - wall
        step = {'kind': 'battle', 'before': old['before'], **result}
        assert step == old
        R.clock_input(gc, config)
        expected = R.replay(selection['seed'], prefix + [old], config)
        assert R.fingerprint(gc) == R.fingerprint(expected)
        if index:
            records.append({**selection, 'wall_ns': wall_ns, 'cpu_ns': cpu_ns,
                'simulations': result['simulations'], 'matched': True, 'fingerprint': R.fingerprint(gc)})
    H.write_json(root / f'timing/round-{round_index}.json', {'arm': identity['arm'],
        'round': round_index, 'identity': identity, 'records': records,
        'wall_ns': sum(r['wall_ns'] for r in records), 'cpu_ns': sum(r['cpu_ns'] for r in records)})


def run(root):
    S.verify_files(root)
    plan = H.read_json(root / 'plan.json')
    probe = Path(plan['probe'])
    proof = H.read_json(probe / 'completion-verification.json')
    assert proof['status'] == 'complete' and proof['whole_run_gate_passed']
    assert proof['hashes']['report.json'] == S.sha(probe / 'report.json')
    assert proof['hashes']['plan.json'] == plan['probe_plan_sha256'] == S.sha(probe / 'plan.json')
    if plan.get('control_probe'):
        control = Path(plan['control_probe'])
        checked = H.read_json(control / 'completion-verification.json')
        assert checked['status'] == 'complete' and checked['whole_run_gate_passed']
        assert checked['hashes']['report.json'] == S.sha(control / 'report.json')
        assert checked['hashes']['plan.json'] == plan['control_probe_plan_sha256'] == S.sha(control / 'plan.json')
        assert checked['engine_shas']['rebuilt'] == S.sha(root / 'rebuilt_control/engine/slaythespire.cpython-312-darwin.so')
        subprocess.run([sys.executable, str(root / 'rebuilt_control/run_speed_validation.py'),
            'whole', '--root', str(root / 'rebuilt_control')], check=True)
        assert H.read_json(root / 'rebuilt_control/whole-verification.json')['matched'] == 64
    subprocess.run([sys.executable, str(root / 'candidate/run_speed_validation.py'),
        'whole', '--root', str(root / 'candidate')], check=True)
    whole_report = H.read_json(root / 'candidate/whole-verification.json')
    assert whole_report['matched'] == 64
    for round_index, order in enumerate(plan['round_orders']):
        for arm in order:
            H.write_json(root / 'status.json', {'stage': 'isolated_timing', 'round': round_index + 1,
                'total_rounds': len(plan['round_orders']), 'arm': arm})
            subprocess.run([sys.executable, str(root / arm / 'run_speed_validation.py'),
                'timing', '--root', str(root / arm), '--round', str(round_index)], check=True)
    pairs, indexes = [], []
    for i in range(len(plan['round_orders'])):
        rows = {arm: H.read_json(root / arm / f'timing/round-{i}.json') for arm in ('baseline', 'candidate')}
        old, new = rows['baseline'], rows['candidate']
        assert len(old['records']) == len(new['records']) == 16
        assert [{k:v for k,v in r.items() if k not in ('cpu_ns', 'wall_ns')} for r in old['records']] == [
            {k:v for k,v in r.items() if k not in ('cpu_ns', 'wall_ns')} for r in new['records']]
        pairs.append({'round': i, 'baseline_wall_ns': old['wall_ns'], 'candidate_wall_ns': new['wall_ns'],
            'baseline_cpu_ns': old['cpu_ns'], 'candidate_cpu_ns': new['cpu_ns'],
            'time_reduction': 1 - new['wall_ns'] / old['wall_ns']})
        for arm in rows:
            path = root / arm / f'timing/round-{i}.json'
            indexes.append({'path': str(path.relative_to(root)), 'sha256': S.sha(path)})
    reductions = [p['time_reduction'] for p in pairs]
    rng = random.Random(plan['bootstrap_seed'])
    boot = sorted(statistics.median(rng.choices(reductions, k=len(reductions)))
                  for _ in range(plan['bootstrap_round_resamples']))
    interval = [boot[int(.025 * len(boot))], boot[int(.975 * len(boot))]]
    median = statistics.median(reductions)
    accepted = median >= plan['gate']['minimum_median_paired_time_reduction'] and interval[0] > 0
    report = {'experiment': plan['experiment'], 'status': 'complete', 'battle_matches': proof['states_per_arm'],
        'whole_trace_matches': whole_report['matched'], 'whole_strata': whole_report['strata'],
        'timing_states': 16, 'paired_rounds': len(pairs), 'timed_battles_each_arm': 16 * len(pairs),
        'median_paired_time_reduction': median, 'paired_bootstrap_95': interval,
        'total_timed_baseline_ns': sum(p['baseline_wall_ns'] for p in pairs),
        'total_timed_candidate_ns': sum(p['candidate_wall_ns'] for p in pairs),
        'pairs': pairs, 'performance_gate_passed': accepted,
        'limits': plan['limits'], 'runner_sha256': S.sha(__file__),
        'hashes': {'probe_verification': S.sha(probe / 'completion-verification.json'),
                   'whole_verification': S.sha(root / 'candidate/whole-verification.json')}}
    if plan.get('control_probe'):
        report['rebuilt_control_whole_matches'] = 64
        report['hashes']['control_probe_verification'] = S.sha(Path(plan['control_probe']) / 'completion-verification.json')
        report['hashes']['rebuilt_control_whole_verification'] = S.sha(root / 'rebuilt_control/whole-verification.json')
    H.write_json(root / 'timing-result-index.json', indexes)
    H.write_json(root / 'report.json', report)
    S.verify_files(root)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': 'complete',
        'performance_gate_passed': accepted})
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'whole', 'timing'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--round', type=int, default=0)
    parser.add_argument('--probe', type=Path)
    parser.add_argument('--experiment', default='E30')
    parser.add_argument('--control-probe', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare': prepare(root, args.probe.resolve() if args.probe else None,
        args.experiment, args.control_probe.resolve() if args.control_probe else None)
    elif args.command == 'whole': whole(root)
    elif args.command == 'timing': timing(root, args.round)
    else: run(root)
