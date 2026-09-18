"""Collect distinct natural-start training Heart wins, then pause before training."""
import argparse
from collections import Counter
import fcntl
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import traceback

import heart_bulk_collect as C

H, R = C.H, C.R
ROLES = ('train', 'validation', 'final_test', 'acceptance', 'training_or_development')


def verify_frozen(root):
    for name, expected in H.read_json(root / 'manifest.json')['frozen_files'].items():
        if C.sha(root / name) != expected:
            raise ValueError('frozen collection input changed: ' + str(root / name))


def seed_inventory(runs, exclude=None):
    used, held_out, provenance = set(), set(), []
    for path in sorted(runs.glob('*/seeds.json')):
        if exclude is not None and path.parent == exclude:
            continue
        data = H.read_json(path)
        for role in ROLES:
            used.update(data.get(role, []))
        for role in ('validation', 'final_test', 'acceptance'):
            held_out.update(data.get(role, []))
        provenance.append({'path': str(path), 'sha256': C.sha(path)})
    legacy = set(H.A.read_seeds('eval_seeds_50.txt'))
    return used | legacy, held_out | legacy, provenance


def draw_seeds(count, used):
    values, assigned = [], set()
    while len(values) < count:
        seed = 10000000 + secrets.randbelow(1990000000)
        if seed not in used and seed not in assigned:
            assigned.add(seed)
            values.append(seed)
    return values


def verify_success(directory, seed, config, replay=False, require_original_terminal=True):
    result_path = directory / f'results/{seed}.json'
    row = H.read_json(result_path)
    if (row.get('seed') != seed or row.get('status') != 'heart_win'
            or row.get('target') != 1.0 or not row.get('replay_verified')
            or row.get('act') != 4 or row.get('keys') != [True, True, True]
            or row.get('hp', 0) <= 0):
        raise ValueError(f'invalid winning result: {result_path}')
    trace, encoded = directory / f'episodes/{seed}.json.gz', directory / f'encoded/{seed}.json.gz'
    if C.sha(trace) != row['trace_sha256'] or C.sha(encoded) != row['encoded_sha256']:
        raise ValueError(f'winning data checksum mismatch: {seed}')
    run, groups = H.read_json(trace), H.read_json(encoded)
    for key in ('seed', 'status', 'act', 'floor', 'hp', 'keys', 'target'):
        if run[key] != row[key]:
            raise ValueError(f'winning trace/result mismatch: {seed}/{key}')
    if not run['prefix'] or not groups or len(groups) != row['decision_count']:
        raise ValueError(f'winning trajectory omitted its decisions: {seed}')
    if any(group['seed'] != seed for group in groups):
        raise ValueError(f'winning decisions belong to a different seed: {seed}')
    if require_original_terminal and (not row.get('terminal_state_verified')
            or not run.get('terminal_fingerprint')
            or run['terminal_fingerprint'] != row.get('terminal_fingerprint')):
        raise ValueError(f'winning terminal state/RNG was not verified: {seed}')
    receipt = {'seed': seed, 'directory': str(directory), 'result_sha256': C.sha(result_path),
               'trace_sha256': C.sha(trace), 'encoded_sha256': C.sha(encoded),
               'decision_count': len(groups), 'floor': row['floor'], 'hp': row['hp'],
               'natural_replay_verified': True,
               'original_terminal_fingerprint_available': bool(run.get('terminal_fingerprint'))}
    if replay:
        if R.training_samples(run, config) != groups:
            raise ValueError(f'replayed winning decisions changed: {seed}')
        receipt['replayed_terminal_fingerprint'] = R.fingerprint(R.replay(seed, run['prefix'], config))
    return receipt


class Progress:
    def __init__(self, root, plan, config):
        self.root, self.plan, self.config = root, plan, config
        self.wins = {row['seed']: row for row in H.read_json(root / 'baseline-successes.json')}
        self.seen, self.statuses = set(), Counter()
        self.decisions, self.last_flush, self.reason = 0, 0, None
        self.allowed = set(H.read_json(root / 'seeds.json')['train'])
        self.baseline_seeds = set(plan['baseline_training_seeds'])
        self.last_batch = None

    def observe(self, row):
        seed = row['seed']
        if seed not in self.allowed or seed in self.baseline_seeds:
            raise ValueError('result belongs to an unassigned or repeated baseline seed')
        if seed in self.seen:
            return self.should_stop()
        self.seen.add(seed)
        status = row.get('status', 'missing_status')
        self.statuses[status] += 1
        self.decisions += row.get('decision_count', 0)
        valid = (R.target(status) is not None and row.get('target') == R.target(status)
                 and row.get('replay_verified') and row.get('terminal_state_verified'))
        if not valid:
            self.reason = 'requires_data_review'
        if status == 'heart_win' and valid:
            self.wins[seed] = verify_success(self.root, seed, self.config)
            self.flush(force=True)
        self.flush()
        return self.should_stop()

    def should_stop(self):
        if (self.root / 'STOP').exists():
            self.reason = self.reason or 'paused_by_request'
        return bool(self.reason) or len(self.wins) >= self.plan['target_successes']

    def flush(self, force=False, stage=None):
        if not force and time.monotonic() - self.last_flush < 15:
            return
        self.last_flush = time.monotonic()
        if shutil.disk_usage(self.root).free < 2 * 1024 ** 3:
            self.reason = self.reason or 'paused_low_disk'
        status = {'stage': stage or self.reason or ('finishing_active_games' if self.should_stop()
                                                   else 'collecting'),
                  'controller_pid': os.getpid(), 'updated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'target_successes': self.plan['target_successes'], 'unique_successes': len(self.wins),
                  'baseline_successes': self.plan['baseline_successes'],
                  'new_successes': len(self.wins) - self.plan['baseline_successes'],
                  'remaining_successes': max(0, self.plan['target_successes'] - len(self.wins)),
                  'new_completed': len(self.seen), 'new_statuses': dict(self.statuses),
                  'total_completed': self.plan['baseline_games'] + len(self.seen),
                  'total_decisions': self.plan['baseline_decisions'] + self.decisions,
                  'new_assigned': len(self.allowed), 'batch': self.last_batch,
                  'workers': self.config['workers'], 'training_started': False,
                  'evaluation_started': False, 'training_only': True}
        H.write_json(self.root / 'success-index.json', sorted(self.wins.values(), key=lambda row: row['seed']))
        H.write_json(self.root / 'status.json', status)
        H.append_metric(self.root, status)


def reserve_batch(root, config):
    used, _, provenance = seed_inventory(Path(H.read_json(root / 'plan.json')['runs_directory']))
    current = H.read_json(root / 'seeds.json')['train']
    # Include immutable reservations if a prior process stopped between the two writes.
    reserved = {s for p in (root / 'batches').glob('*/seeds.json') for s in H.read_json(p)['train']}
    batch = root / 'batches' / f'{len(list((root / "batches").glob("*"))) + 1:05d}'
    batch.mkdir(parents=True)
    seeds = draw_seeds(config['collection_batch_size'], used | set(current) | reserved)
    jobs = [{'mode': 'prefix', 'seed': seed, 'directory': str(root),
             'output': str(root / f'results/{seed}.json')} for seed in seeds]
    H.write_json(batch / 'seeds.json', {'train': seeds})
    H.write_json(batch / 'jobs.json', jobs)
    H.write_json(batch / 'reservation.json', {'excluded_seeds': len(used | set(current) | reserved),
                                             'seed_provenance': provenance})
    H.write_json(batch / 'manifest.json', {'frozen_files': {
        name: C.sha(batch / name) for name in ('seeds.json', 'jobs.json', 'reservation.json')}})
    H.write_json(root / 'seeds.json', {'train': sorted(set(current) | reserved | set(seeds))})
    return batch


def collect(root):
    root = Path(root).resolve()
    with (root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_frozen(root)
        plan, config = H.read_json(root / 'plan.json'), H.read_json(root / 'config.json')
        if (root / 'report.json').exists():
            return
        # Restore the public training reservation index before accepting any result.
        reserved = {s for p in (root / 'batches').glob('*/seeds.json') for s in H.read_json(p)['train']}
        H.write_json(root / 'seeds.json', {'train': sorted(reserved)})
        progress = Progress(root, plan, config)
        for path in sorted((root / 'results').glob('*.json')):
            progress.observe(H.read_json(path))
        progress.flush(force=True)
        while not progress.should_stop():
            batch = next((p for p in sorted((root / 'batches').glob('*'))
                          if not (p / 'report.json').exists()
                          or H.read_json(p / 'report.json')['completed'] < len(H.read_json(p / 'jobs.json'))), None)
            if batch is None:
                batch = reserve_batch(root, config)
            verify_frozen(batch)
            jobs = H.read_json(batch / 'jobs.json')
            _, held_out, _ = seed_inventory(Path(plan['runs_directory']), exclude=root)
            if set(job['seed'] for job in jobs) & held_out:
                raise ValueError('assigned collection seed overlaps a held-out partition')
            progress.allowed.update(job['seed'] for job in jobs)
            progress.last_batch = batch.name
            rows = C.run_collection_jobs(batch, jobs, config,
                        time.monotonic() + config['collection_seconds'], on_result=progress.observe)
            H.write_json(batch / 'report.json', {'assigned': len(jobs), 'completed': len(rows),
                'summary': H.summarize(rows), 'stopped_at_success_target': len(progress.wins) >= plan['target_successes']})
            if len(rows) != len(jobs) and not progress.should_stop():
                progress.reason = 'requires_incomplete_batch_review'
            progress.flush(force=True)
        if progress.reason:
            progress.flush(force=True, stage=progress.reason)
            return
        progress.flush(force=True, stage='verifying_successes')
        for seed, receipt in list(progress.wins.items()):
            source = Path(receipt['directory'])
            progress.wins[seed] = verify_success(source, seed, config, replay=True,
                                                 require_original_terminal=(source == root))
        progress.flush(force=True, stage='complete_paused')
        H.write_json(root / 'report.json', {**H.read_json(root / 'status.json'),
            'winning_seeds': sorted(progress.wins), 'all_successes_replayed': True,
            'scope': plan['scope'], 'final_goal_unseen_win_rate': 0.10})


def launch(baseline, output, target=160, engine=None):
    baseline, root = Path(baseline).resolve(), Path(output).resolve()
    verify_frozen(baseline)
    report = H.read_json(baseline / 'report.json')
    if report['status'] != 'complete' or not report['all_natural_prefixes_replay_verified']:
        raise ValueError('baseline collection requires review')
    training = H.read_json(baseline / 'seeds.json')['train']
    seeds = report['winning_seeds']
    if target < 1 or len(set(seeds)) != len(seeds) or not set(seeds) <= set(training):
        raise ValueError('invalid baseline success seeds or target')
    _, held_out, _ = seed_inventory(baseline.parent)
    if set(training) & held_out:
        raise ValueError('baseline training seeds overlap held-out partitions')
    root.mkdir(parents=True, exist_ok=False)
    origin = C.freeze_runtime(baseline, root, engine)
    shutil.copy2(Path(__file__), root / 'source' / Path(__file__).name)
    shutil.copy2(Path(C.T.__file__), root / 'source/heart_role_teacher.py')
    if C.sha(root / 'source/heart_role_teacher.py') != H.read_json(baseline / 'manifest.json')['teacher_sha256']:
        raise ValueError('fixed collection policy differs from baseline')
    config = {**H.read_json(baseline / 'config.json'), 'workers': 8,
              'collection_games_per_worker': 32, 'collection_batch_size': 1024}
    if (config['simulations'], config['boss_multiplier'], config['ascension'], config['character'],
            config['prismatic_shard'], config['target']) != (8000, 3.0, 20, 'IRONCLAD', False, 'HEART'):
        raise ValueError('collection scope or combat budget changed')
    H.write_json(root / 'config.json', config)
    (root / 'eval_seeds_50.txt').write_text(''.join(f'{seed}\n' for seed in H.A.read_seeds('eval_seeds_50.txt')))
    receipts = [verify_success(baseline, seed, config, replay=True, require_original_terminal=False)
                for seed in seeds]
    H.write_json(root / 'baseline-successes.json', receipts)
    H.write_json(root / 'plan.json', {'target_successes': target, 'baseline_successes': len(seeds),
        'baseline_directory': str(baseline), 'baseline_report_sha256': C.sha(baseline / 'report.json'),
        'baseline_games': report['summary']['runs'], 'baseline_decisions': report['decision_count'],
        'baseline_training_seeds': training, 'runs_directory': str(baseline.parent),
        'scope': 'Ironclad A20 natural start, all keys and Heart; Prismatic Shard excluded',
        'counting': 'distinct training seeds with natural-prefix state/RNG replay and verified Heart terminal',
        'sampling': 'fixed RoleTeacher(1), all outcomes retained, independent disjoint new seeds',
        'stopping': 'stop assigning at target; retain and finish in-flight games, allowing extra wins',
        'training_followup': 'paused; no neural training or model evaluation authorized in this collection',
        'final_goal_unseen_win_rate': 0.10, 'runtime_origin': origin})
    H.write_json(root / 'seeds.json', {'train': []})
    (root / 'batches').mkdir()
    frozen = {str(p.relative_to(root)): C.sha(p) for p in root.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p != root / 'seeds.json'}
    H.write_json(root / 'manifest.json', {'frozen_files': frozen, 'training_only': True})
    env = {**os.environ, 'STS_LIGHTSPEED_BUILD': str(root / 'engine'), 'ASC': '20',
           'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    with (root / 'stdout.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, str(root / 'source/heart_success_collect.py'), 'run', str(root)],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    H.write_json(root / 'launch.json', {'pid': child.pid, 'directory': str(root), 'target_successes': target})
    print({'pid': child.pid, 'directory': str(root), 'baseline_successes': len(seeds),
           'target_successes': target, 'training_started': False}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('launch')
    start.add_argument('baseline')
    start.add_argument('output')
    start.add_argument('--target', type=int, default=160)
    start.add_argument('--engine')
    run = sub.add_parser('run')
    run.add_argument('directory')
    args = parser.parse_args()
    if args.command == 'launch':
        launch(args.baseline, args.output, args.target, args.engine)
    else:
        try:
            collect(args.directory)
        except Exception:
            H.write_json(Path(args.directory) / f'controller-error-{os.getpid()}.json',
                         {'error': traceback.format_exc(), 'pid': os.getpid(), 'training_started': False})
            raise
