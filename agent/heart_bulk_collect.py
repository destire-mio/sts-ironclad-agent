"""Collect disjoint complete A20 games, with replay-verified decision shards."""
import argparse
from collections import deque
import hashlib
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import traceback

import heart_train as H
import heart_runtime as R
import heart_role_teacher as T


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def worker(job, config):
    root = Path(job['directory'])
    try:
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
        run = R.rollout(job['seed'], config, gc=gc, net=T.RoleTeacher(1), record=True,
                        record_samples=False)
        R.clock_input(gc, config)
        run['terminal_fingerprint'] = R.fingerprint(gc)
        valid = R.target(run['status']) is not None
        trace = root / f"episodes/{job['seed']}.json.gz"
        encoded = root / f"encoded/{job['seed']}.json.gz"
        # The full prefix reconstructs observations. Avoid storing a second copy
        # of all decision matrices and selected roots inside the raw trace.
        run['samples'] = []
        run['roots'] = []
        # Preserve the raw trajectory even if replay validation rejects its label.
        H.write_json(trace, run)
        groups = R.training_samples(run, config) if valid else []
        H.write_json(encoded, groups)
        result = {k: v for k, v in run.items() if k not in ('prefix', 'samples', 'roots')}
        result.update(decision_count=len(groups), replay_verified=valid,
                      terminal_state_verified=valid,
                      trace_sha256=sha(trace), encoded_sha256=sha(encoded))
        if run['status'] == 'heart_win':
            (root / 'successes').mkdir(exist_ok=True)
            shutil.copy2(trace, root / f"successes/{job['seed']}.json.gz")
        H.write_json(job['output'], result)
    except Exception:
        H.write_json(job['output'], {'seed': job['seed'], 'status': 'data_error',
                     'target': None, 'replay_verified': False, 'error': traceback.format_exc()})


def _serve(connection, config, worker_fn):
    """A fresh GameContext is constructed by worker for every assigned seed."""
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    try:
        while True:
            job = connection.recv()
            if job is None:
                return
            worker_fn(job, config)
            connection.send(job['seed'])
    finally:
        connection.close()


def run_collection_jobs(directory, jobs, config, deadline, worker_fn=worker, on_result=None):
    """Reuse bounded workers; one parent-owned seed and timeout per process.

    A result file is the commit point. A crashed/timed-out process is replaced,
    and only its current, uncommitted seed receives an invalid label. When
    on_result returns true, stop assigning seeds and let active games finish.
    """
    workers = int(config['workers'])
    recycle = int(config.get('collection_games_per_worker', 32))
    if workers < 1 or recycle < 1:
        raise ValueError('workers and collection_games_per_worker must be positive')
    directory = Path(directory)
    pending = deque(job for job in jobs if not Path(job['output']).exists())
    total, completed = len(jobs), len(jobs) - len(pending)
    context, active = mp.get_context('spawn'), []
    last_progress = 0.0
    stop_requested = False
    if on_result is not None:
        for job in jobs:
            if Path(job['output']).exists():
                stop_requested = bool(on_result(H.read_json(job['output']))) or stop_requested

    def assign(slot, job):
        slot.update(job=job, started=time.monotonic(), send_failed=False)
        try:
            slot['connection'].send(job)
        except (BrokenPipeError, EOFError, OSError):
            slot['send_failed'] = True

    def retire(slot, graceful=False):
        process = slot['process']
        if graceful and process.is_alive():
            try:
                slot['connection'].send(None)
            except (BrokenPipeError, EOFError, OSError):
                pass
            process.join(timeout=1)
        if process.is_alive():
            process.kill()
        process.join()
        slot['connection'].close()
        process.close()

    try:
        while (pending and not stop_requested) or active:
            now = time.monotonic()
            for slot in list(active):
                process, connection, job = slot['process'], slot['connection'], slot['job']
                done = False
                if connection.poll():
                    try:
                        done = connection.recv() == job['seed']
                    except (EOFError, OSError):
                        pass
                timed_out = now >= deadline or now - slot['started'] >= config['prefix_timeout']
                if not (done or timed_out or slot['send_failed'] or not process.is_alive()):
                    continue
                if timed_out and not done and process.is_alive():
                    process.kill()
                    process.join()
                output = Path(job['output'])
                if not output.exists():
                    H.write_json(output, {'seed': job['seed'],
                        'status': 'timeout' if timed_out else 'process_error',
                        'target': None, 'replay_verified': False, 'exitcode': process.exitcode})
                completed += 1
                slot['completed'] += 1
                if on_result is not None:
                    stop_requested = bool(on_result(H.read_json(output))) or stop_requested
                if (not stop_requested and done and process.is_alive() and pending and time.monotonic() < deadline
                        and slot['completed'] < recycle):
                    assign(slot, pending.popleft())
                else:
                    retire(slot, graceful=done)
                    active.remove(slot)
            while (not stop_requested and pending and len(active) < workers
                   and time.monotonic() < deadline):
                parent, child = context.Pipe()
                process = context.Process(target=_serve, args=(child, config, worker_fn))
                slot = {'process': process, 'connection': parent, 'completed': 0}
                try:
                    process.start()
                except BaseException:
                    parent.close()
                    child.close()
                    raise
                child.close()
                active.append(slot)
                assign(slot, pending.popleft())
            now = time.monotonic()
            if now - last_progress >= 15 or completed == total or now >= deadline:
                status = {'stage': 'collect_complete_training_games', 'completed': completed,
                          'total': total, 'active_workers': len(active),
                          'controller_pid': os.getpid(),
                          'seconds_remaining': max(0, round(deadline - now))}
                H.write_json(directory / 'status.json', status)
                H.append_metric(directory, status)
                last_progress = now
            if now >= deadline and not active:
                break
            if active:
                # Completion notifications refill slots without a polling sleep.
                wait([item for slot in active
                      for item in (slot['connection'], slot['process'].sentinel)], timeout=0.2)
    finally:
        for slot in active:
            retire(slot)
    return [H.read_json(job['output']) for job in jobs if Path(job['output']).exists()]


def collect(directory):
    root = Path(directory).resolve()
    manifest = H.read_json(root / 'manifest.json')
    for name, expected in manifest['frozen_files'].items():
        if sha(root / name) != expected:
            raise ValueError('frozen collection input changed: ' + name)
    if (root / 'report.json').exists():
        raise ValueError('collection already completed')
    config = H.read_json(root / 'config.json')
    jobs = H.read_json(root / 'jobs.json')
    started = time.monotonic()
    runs = run_collection_jobs(root, jobs, config, started + config['collection_seconds'])
    summary = H.summarize(runs)
    complete = (summary['runs'] == len(jobs) and summary['valid_terminal'] == len(jobs)
                and all(r.get('replay_verified') for r in runs))
    report = {'status': 'complete' if complete else 'requires_data_review', 'requested': len(jobs),
              'summary': summary, 'decision_count': sum(r.get('decision_count', 0) for r in runs),
              'winning_seeds': sorted(r['seed'] for r in runs if r.get('status') == 'heart_win'),
              'all_natural_prefixes_replay_verified': complete,
              'elapsed_seconds': time.monotonic() - started, 'training_only': True}
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'status.json', {'stage': 'finished', **report})
    print(report, flush=True)


def freeze_runtime(parent, root, engine=None):
    """Freeze this collector with its matching runtime, not an older parent's code."""
    modules = ([Path(H.A.sts.__file__).resolve()] if engine is None
               else list(Path(engine).resolve().glob('slaythespire*.so')))
    if len(modules) != 1:
        raise ValueError('engine directory must contain exactly one simulator module')
    shutil.copytree(parent / 'engine', root / 'engine')
    for previous in (root / 'engine').glob('slaythespire*.so'):
        previous.unlink()
    shutil.copy2(modules[0], root / 'engine' / modules[0].name)
    (root / 'source').mkdir()
    for name in ('armG_train.py', 'heart_runtime.py', 'heart_train.py', 'heart_guided.py',
                 'heart_bulk_collect.py'):
        shutil.copy2(Path(__file__).resolve().parent / name, root / 'source' / name)
    return {'engine': str(modules[0]), 'source': str(Path(__file__).resolve().parent)}


def launch(parent, output, count=10000, engine=None):
    parent, root = Path(parent).resolve(), Path(output).resolve()
    for name, expected in H.read_json(parent / 'manifest.json')['frozen_files'].items():
        if sha(parent / name) != expected:
            raise ValueError('parent frozen input changed: ' + name)
    if count <= 0:
        raise ValueError('additional game count must be positive')
    used, provenance = set(), []
    for path in sorted(parent.parent.glob('*/seeds.json')):
        data = H.read_json(path)
        for role in ('train', 'validation', 'final_test', 'acceptance', 'training_or_development'):
            used.update(data.get(role, []))
        provenance.append({'path': str(path), 'sha256': sha(path)})
    used.update(H.A.read_seeds('eval_seeds_50.txt'))
    values, assigned = [], set()
    while len(values) < count:
        seed = 10000000 + secrets.randbelow(1990000000)
        if seed not in used and seed not in assigned:
            assigned.add(seed)
            values.append(seed)
    root.mkdir(parents=True, exist_ok=False)
    runtime_origin = freeze_runtime(parent, root, engine)
    teacher = parent.parent / 'heart-role-collection-20260915-01/heart_role_teacher.py'
    if sha(teacher) != sha(Path(T.__file__)):
        raise ValueError('collection teacher differs from the existing dataset teacher')
    shutil.copy2(teacher, root / 'source/heart_role_teacher.py')
    config = {**H.read_json(parent / 'config.json'), 'workers': 8,
              'collection_games_per_worker': 32,
              'collection_seconds': 21600, 'collection_policy': 'fixed_role_teacher_1'}
    jobs = [{'mode': 'prefix', 'seed': seed, 'directory': str(root),
             'output': str(root / f'results/{seed}.json')} for seed in values]
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'seeds.json', {'train': values})
    H.write_json(root / 'jobs.json', jobs)
    H.write_json(root / 'plan.json', {'additional_independent_training_games': count,
        'excluded_historical_seeds': len(used), 'seed_provenance': provenance,
        'scope': 'Ironclad A20 natural start, all keys and Heart; Prismatic Shard excluded',
        'sampling': 'all complete outcomes; no selection by floor or victory',
        'encoding': 'every natural prefix replayed with state and RNG checks',
        'training_followup': 'two full dataset passes, including every ordinary decision per pass'})
    frozen = {str(p.relative_to(root)): sha(p) for p in root.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    H.write_json(root / 'manifest.json', {'frozen_files': frozen, 'parent': str(parent),
        'training_only': True, 'teacher_sha256': sha(teacher), 'runtime_origin': runtime_origin})
    env = {**os.environ, 'STS_LIGHTSPEED_BUILD': str(root / 'engine'), 'ASC': '20',
           'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    with (root / 'stdout.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, str(root / 'source/heart_bulk_collect.py'), 'run', str(root)],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    H.write_json(root / 'launch.json', {'pid': child.pid, 'directory': str(root)})
    print({'pid': child.pid, 'training_seeds': count, 'excluded_historical_seeds': len(used)}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('launch')
    start.add_argument('parent')
    start.add_argument('output')
    start.add_argument('--count', type=int, default=10000)
    start.add_argument('--engine', help='Verified simulator build; defaults to the currently loaded module')
    run = sub.add_parser('run')
    run.add_argument('directory')
    args = parser.parse_args()
    if args.command == 'launch':
        launch(args.parent, args.output, args.count, args.engine)
    else:
        collect(args.directory)
