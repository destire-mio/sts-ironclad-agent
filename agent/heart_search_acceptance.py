#!/usr/bin/env python3
"""Frozen paired search acceptance on fresh, historically isolated root seeds."""
import argparse
from collections import Counter
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import heart_branch_training as T

P, H, R, S = T.P, T.H, T.R, T.S
REPO = Path(__file__).resolve().parent.parent


def copy_runtime(source, destination):
    manifest = S.verify_files(source)
    destination.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            path = destination / name
            path.parent.mkdir(exist_ok=True, parents=True)
            shutil.copy2(source / name, path)
    for original, name in [(P.__file__, 'heart_branch_pilot.py'),
            (T.__file__, 'heart_branch_training.py'), (__file__, 'run_acceptance.py')]:
        shutil.copy2(original, destination / name)


def prepare(root, source, baseline, experiment='E19', comparison=None):
    if root.exists(): raise ValueError('use a new acceptance directory')
    S.verify_files(source)
    result = H.read_json(source / 'report.json')
    gate = H.read_json(source / 'acceptance-gate-plan.json')['development_gate']
    if result['status'] != 'complete' or result['execution_faults'] or result['seeds'] != gate['required_valid_games']:
        raise ValueError('incomplete development evidence')
    if result['candidate_wins'] < gate['minimum_heart_wins']:
        raise ValueError('development gate failed; do not spend fresh seeds')
    if (gate.get('maximum_original_wins_lost') is not None
            and result['paired'].get('baseline_only', 0) > gate['maximum_original_wins_lost']):
        raise ValueError('development lost too many original winners; do not spend fresh seeds')
    proof_path = source / 'completion-verification.json'
    if not proof_path.exists() or H.read_json(proof_path).get('status') != 'complete':
        raise ValueError('development completion audit is required before fresh acceptance')
    if S.sha(source / 'model.pt') != S.sha(baseline / 'model.pt'):
        raise ValueError('outside weights changed')
    # Inventory before any new seed files are created; include reservations.
    history, provenance = T.historical_seeds(source.parent)
    seeds = T.fresh_seeds(1024, history)
    T.assert_fresh(seeds, history)
    copy_runtime(baseline, root)
    H.write_json(root / 'historical-seed-provenance.json', provenance)
    H.write_json(root / 'seeds.json', {'acceptance': seeds})
    for arm, origin in [('baseline', baseline), ('candidate', source)]:
        dst = root / arm
        copy_runtime(origin, dst)
        config = H.read_json(dst / 'config.json')
        if (config['simulations'], config['boss_multiplier'], config['ascension'], config['policy_start_floor']) != (8000, 3, 20, 0):
            raise ValueError('unexpected acceptance scope')
        config['workers'] = 4
        H.write_json(dst / 'config.json', config)
        identity = {'arm': arm, 'model_sha256': S.sha(dst / 'model.pt'),
            'engine_sha256': S.sha(dst / 'engine/slaythespire.cpython-312-darwin.so')}
        H.write_json(dst / 'identity.json', identity)
        H.write_json(dst / 'seeds.json', {'acceptance': seeds})
        H.write_json(dst / 'manifest.json', {'frozen_files': {str(p.relative_to(dst)): S.sha(p)
            for p in dst.rglob('*') if p.is_file()}})
    H.write_json(root / 'plan.json', {'experiment': experiment, 'created_at': P.utc(),
        'source': str(source), 'development_report_sha256': S.sha(source / 'report.json'),
        'development_verification_sha256': S.sha(proof_path),
        'source_gate_sha256': S.sha(source / 'acceptance-gate-plan.json'),
        'seeds': len(seeds), 'excluded_historical_or_reserved': len(history),
        'scope': 'Ironclad A20 natural opening, all three keys, double act-three boss, Act Four Heart; Prismatic Shard excluded.',
        'comparison': comparison or 'Same original outside NN, original versus frozen rollout search; 8000 per search, boss x3. No outside lookahead or act-one candidate weights.',
        'selection': 'Both systems frozen before drawing fresh seeds. All assigned seeds retained; no seed selection or early stopping on win rate.',
        'resources': 'Two concurrent arms, four single-thread workers each; 7200 seconds per arm including winner reruns. Original episode 120-second soft and process 150-second hard guards.',
        'verification': 'Every valid terminal naturally replayed. Every Heart winner rerun from scratch with model/MCTS, with exact actions, terminal and RNG match. The first executed-action divergence for every valid pair must be a combat decision at an identical complete state/RNG.',
        'statistics': 'Heart wins over all 1024 assigned seeds, paired transitions for valid pairs, exact paired test, Wilson 95 percent marginal intervals. Errors and truncations remain separate from game deaths.',
        'target': 'Observed Heart success >=10 percent (at least 103/1024), distinct from a population lower confidence bound >=10 percent.',
        'post_acceptance_decision': 'With complete verification, more candidate wins and paired exact p <0.05 support using this frozen combat profile for the next training experiment. This is separate from the 10 percent target. All acceptance seeds are then retired from training and further fresh acceptance; subsequent policy changes require a new evaluation pool.',
        'limitations': 'Simulator and existing planner information access. Internal replay does not establish original Java parity. No training or tuning on these seeds.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and p != root / 'manifest.json'}})


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        identity = job['identity']
        if S.sha(root / 'engine/slaythespire.cpython-312-darwin.so') != identity['engine_sha256']:
            raise ValueError('engine changed')
        if S.sha(R.sts.__file__) != identity['engine_sha256']:
            raise ValueError('loaded native engine differs from the frozen arm')
        row = T.natural_episode(job['seed'], root / 'model.pt', identity['model_sha256'], config)
        row.update(identity=identity)
    except Exception:
        row = {'seed': job['seed'], 'status': 'execution_error', 'target': None, 'error': traceback.format_exc()}
    H.write_json(job['output'], row)


def run_arm(root):
    S.verify_files(root)
    identity = H.read_json(root / 'identity.json')
    seeds, config = H.read_json(root / 'seeds.json')['acceptance'], H.read_json(root / 'config.json')
    jobs = [{'mode': 'prefix', 'seed': seed, 'root': str(root), 'identity': identity,
        'output': str(root / f'episodes/{seed}.json.gz')} for seed in seeds]
    deadline = time.monotonic() + 7200
    rows = H.run_jobs(root, jobs, config, 'fresh_natural_games', deadline, worker_fn=worker)
    def valid(row):
        return row.get('identity') == identity and T.valid_episode(row, row.get('seed'), identity['model_sha256'])
    faults = [r for r in rows if not valid(r)]
    winners = [r for r in rows if valid(r) and r['status'] == 'heart_win']
    repeat_jobs = [{'mode': 'prefix', 'seed': r['seed'], 'root': str(root), 'identity': identity,
        'output': str(root / f'repeated/{r["seed"]}.json.gz')} for r in winners]
    repeated = H.run_jobs(root, repeat_jobs, config, 'fresh_winner_reruns', deadline, worker_fn=worker) if repeat_jobs else []
    repeats = []
    for original, again, job in zip(winners, repeated, repeat_jobs):
        matches = valid(again) and original['prefix'] == again['prefix'] and P.terminal_signature(original) == P.terminal_signature(again)
        repeats.append({'seed': original['seed'], 'matched': matches, 'sha256': S.sha(job['output'])})
    complete = len(rows) == len(seeds) and not faults and all(r['matched'] for r in repeats) and len(repeated) == len(winners)
    report = {'status': 'complete' if complete else 'execution_review_required', 'identity': identity,
        'assigned_seeds': len(seeds), 'results': len(rows), 'execution_faults': len(faults),
        'heart_wins': len(winners), 'winning_seeds': [r['seed'] for r in winners],
        'terminal_distribution': dict(Counter(f'{r.get("act")}:{r.get("status")}' for r in rows)),
        'winner_reruns': repeats, 'search_simulations': sum(r.get('simulations', 0) for r in rows),
        'finished_at': P.utc()}
    H.write_json(root / 'result-index.json', [{'seed': j['seed'], 'sha256': S.sha(j['output'])} for j in jobs if Path(j['output']).exists()])
    H.write_json(root / 'errors.json', faults)
    H.write_json(root / 'report.json', report)
    S.verify_files(root)
    H.write_json(root / 'status.json', {'stage': 'finished', **report})


def wilson(wins, total):
    z = 1.959963984540054
    p, denominator = wins / total, 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [center-half, center+half]


def first_search_change(old, new):
    """The first divergence must be combat actions from the same live state."""
    for index, (a, b) in enumerate(zip(old['prefix'], new['prefix'])):
        # Search effort may change without changing the executed game actions.
        if {k: v for k, v in a.items() if k != 'simulations'} == {k: v for k, v in b.items() if k != 'simulations'}:
            continue
        if (a.get('kind') != 'battle' or b.get('kind') != 'battle' or a['before'] != b['before']
                or a.get('actions') == b.get('actions')):
            raise ValueError(f'first divergence is not a same-state combat decision: {old["seed"]}:{index}')
        return {'prefix_index': index, 'kind': 'battle', 'before': a['before']}
    if len(old['prefix']) != len(new['prefix']) or P.terminal_signature(old) != P.terminal_signature(new):
        raise ValueError(f'identical actions did not produce an identical terminal: {old["seed"]}')
    return {'kind': 'unchanged'}


def run(root):
    S.verify_files(root)
    processes, streams = [], []
    for arm in ('baseline', 'candidate'):
        stream = (root / arm / 'stdout.log').open('a')
        streams.append(stream)
        processes.append(subprocess.Popen([sys.executable, str(root / arm / 'run_acceptance.py'),
            'arm', '--root', str(root / arm)], stdout=stream, stderr=subprocess.STDOUT))
    H.write_json(root / 'status.json', {'stage': 'paired_fresh_acceptance', 'pids': [p.pid for p in processes]})
    exits = [p.wait() for p in processes]
    for stream in streams: stream.close()
    if any(exits): raise ValueError('acceptance arm failed; inspect preserved logs')
    reports = {arm: H.read_json(root / arm / 'report.json') for arm in ('baseline', 'candidate')}
    seeds = H.read_json(root / 'seeds.json')['acceptance']
    pairs, counts, first_changes = [], Counter(), Counter()
    for seed in seeds:
        rows = {arm: H.read_json(root / arm / f'episodes/{seed}.json.gz') for arm in reports}
        good = all(T.valid_episode(rows[arm], seed, reports[arm]['identity']['model_sha256'])
            and rows[arm].get('identity') == reports[arm]['identity'] for arm in rows)
        change = None
        if not good: category = 'execution_fault_pair'
        else:
            change = first_search_change(rows['baseline'], rows['candidate'])
            first_changes[change['kind']] += 1
            old, new = rows['baseline']['status'] == 'heart_win', rows['candidate']['status'] == 'heart_win'
            category = 'both_win' if old and new else 'baseline_only' if old else 'candidate_only' if new else 'both_fail'
        counts[category] += 1
        pairs.append({'seed': seed, 'category': category, 'first_change': change, **{arm: {k: row.get(k) for k in
            ('status', 'act', 'floor', 'hp', 'keys', 'terminal_fingerprint')} for arm, row in rows.items()}})
    discordant = counts['baseline_only'] + counts['candidate_only']
    pvalue = min(1.0, 2 * sum(math.comb(discordant, i) for i in range(min(counts['baseline_only'], counts['candidate_only']) + 1)) / 2**discordant) if discordant else 1.0
    complete = all(r['status'] == 'complete' for r in reports.values()) and not counts['execution_fault_pair']
    result = {'experiment': H.read_json(root / 'plan.json')['experiment'], 'status': 'complete' if complete else 'execution_review_required',
        'seeds': len(seeds), 'arms': reports, 'paired': dict(counts), 'paired_exact_p': pvalue,
        'first_change_verification': dict(first_changes),
        'wilson_95_intervals': {arm: wilson(r['heart_wins'], len(seeds)) for arm, r in reports.items()},
        'observed_ten_percent_target_met': complete and reports['candidate']['heart_wins'] / len(seeds) >= .1,
        'limits': 'One frozen system comparison on fresh simulator root seeds. No original-game parity claim; observed proportion and population uncertainty are separate.'}
    H.write_json(root / 'paired-outcomes.json', pairs)
    H.write_json(root / 'report.json', result)
    S.verify_files(root)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': result['status'],
        'heart_wins': {arm: r['heart_wins'] for arm, r in reports.items()}})
    print(result, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare', 'run', 'arm'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--source', type=Path, default=REPO / 'runs/heart-rollout-development-20260917-01')
    p.add_argument('--baseline', type=Path, default=REPO / 'runs/heart-training-set-evaluation-20260915-01')
    p.add_argument('--experiment', default='E19')
    p.add_argument('--comparison')
    a = p.parse_args()
    if a.command == 'prepare': prepare(a.root.resolve(), a.source.resolve(), a.baseline.resolve(), a.experiment, a.comparison)
    elif a.command == 'arm': run_arm(a.root.resolve())
    else: run(a.root.resolve())
