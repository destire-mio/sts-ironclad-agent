"""Run the registered six-stage E118 collection once in an owned process group."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time
import traceback

import run_collections as C


def members(group):
    rows = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,pgid=,stat=,command='], text=True)
    return [row.strip() for row in rows.splitlines()
            if len(row.split()) >= 5 and row.split()[2] == str(group)]


def cleanup(child):
    group = child.pid
    assert group != os.getpgrp()
    before = members(group)
    if before:
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(group, signal.SIGKILL)
        child.wait(timeout=3)
    remaining = members(group)
    if remaining:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 3
    while remaining and time.monotonic() < deadline:
        time.sleep(.05)
        remaining = members(group)
    return {'initial_members': before, 'remaining_members': remaining,
            'clean': not remaining, 'process_group': group}


def run_owned(root, command, environment, seconds, registration_sha256):
    root = Path(root)
    assert not (root / 'pipeline-process.json').exists(), 'preserve the first execution'
    handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    requested_signal = None

    def interrupted(signum, frame):
        nonlocal requested_signal
        requested_signal = signum
        raise InterruptedError(f'wrapper received signal {signum}')

    code, error, child, cleaned = None, None, None, None
    with (root / 'pipeline.log').open('x') as log:
        try:
            child = subprocess.Popen(command, cwd=root, env=environment,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            if child.poll() is None:
                assert os.getpgid(child.pid) == child.pid
            C.write(root / 'pipeline-process.json', {
                'started_at': datetime.now(timezone.utc).isoformat(), 'wrapper_pid': os.getpid(),
                'pid': child.pid, 'process_group': child.pid, 'command': command,
                'registration_sha256': registration_sha256, 'wrapper_seconds': seconds})
            print(json.dumps({'pid': child.pid, 'process_group': child.pid, 'root': str(root)}), flush=True)
            for signum in handlers:
                signal.signal(signum, interrupted)
            code = child.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            code = 124
        except BaseException:
            code = 128 + requested_signal if requested_signal else 1
            error = traceback.format_exc()
        finally:
            # A second interrupt must not interrupt removal of owned descendants.
            for signum in handlers:
                signal.signal(signum, signal.SIG_IGN)
            try:
                if child is not None:
                    cleaned = cleanup(child)
            finally:
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)
    if cleaned is None or not cleaned['clean']:
        code = code or 1
    result = {'finished_at': datetime.now(timezone.utc).isoformat(), 'exit_code': code,
        'requested_signal': requested_signal, 'error': error, 'cleanup': cleaned,
        'log_sha256': C.sha(root / 'pipeline.log'), 'registration_sha256': registration_sha256}
    C.write(root / 'pipeline-process-exit.json', result)
    return result


def main():
    root = Path(__file__).resolve().parent
    registration = C.read(root / 'execution-registration.json')
    for name, expected in registration['hashes'].items():
        assert C.sha(root / name) == expected, name
    # This runs before process metadata, log files, runtime copies or workers.
    plan, gates = C.source_ready(root)
    probe = C.read(root / 'launcher-probe/completion-verification.json')
    assert probe['status'] == 'passed' and probe['incomplete_source_rejected_before_launch']
    assert probe['launcher_sha256'] == C.sha(root / 'run_pipeline.py')
    assert probe['checker_sha256'] == C.sha(root / 'check-launcher.py')
    assert probe['collector_registration_sha256'] == C.sha(root / 'registration.json')
    assert {case['case'] for case in probe['cases']} == {'normal', 'fault', 'timeout', 'wrapper_SIGTERM'}
    assert all(case['cleanup'] and case['unrelated_job_alive'] for case in probe['cases'])
    for name, expected in probe['hashes'].items():
        assert C.sha(root / 'launcher-probe' / name) == expected, name
    for name in ('execution-started.json', 'pipeline-process.json', 'relic-source', 'joint'):
        assert not (root / name).exists(), 'preserve prior attempt: ' + name
    environment = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    result = run_owned(root, [sys.executable, '-u', str(root / 'run_collections.py'),
        'pipeline', '--root', str(root)], environment, registration['wrapper_seconds'],
        C.sha(root / 'execution-registration.json'))
    if result['exit_code'] == 0:
        C.source_ready(root)
        C.proof(root)
        C.proof(root / 'relic-source', 'label-verification.json')
        C.proof(root / 'joint', 'label-verification.json')
        C.write(root / 'pipeline-execution-verification.json', {
            'status': 'complete', 'cleanup_verified': True, 'optimizer_updates': 0,
            'source_gates': gates, 'collection_completion_sha256': C.sha(root / 'completion-verification.json'),
            'process_exit_sha256': C.sha(root / 'pipeline-process-exit.json')})
    print(json.dumps({k: result[k] for k in ('exit_code', 'requested_signal', 'error')}), flush=True)
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
