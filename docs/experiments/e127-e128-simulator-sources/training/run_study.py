"""Continue this local study after source completion, observing every 20 minutes."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
N = ROOT.parent / 'heart-e121-scale-source-refresh-20260920-01'
COLLECTOR = ROOT.parent / 'heart-e121-simulator-joint-labels-20260920-01'
sys.path.insert(0, str(COLLECTOR))
import run_pipeline as P
read, write, sha = P.C.read, P.C.write, P.C.sha


def registered():
    reg = read(ROOT / 'study-registration.json')
    for path, digest in reg['hashes'].items():
        assert sha(path) == digest, path
    assert reg['observer_interval_seconds'] == 1200
    assert reg['evidence_scope'] == 'simulator_only'
    assert read(COLLECTOR / 'simulator-admission-probe/completion-verification.json')['status'] == 'passed'
    assert read(ROOT / 'training-execution-entry-verification.json')['status'] == 'passed'
    assert not (ROOT / 'source-closed.json').exists()
    return reg


def status(stage, **extra):
    path = ROOT / 'study-status.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({'stage': stage, 'controller_pid': os.getpid(),
        'updated_at': datetime.now(timezone.utc).isoformat(), **extra}, indent=2) + '\n')
    temp.replace(path)


def source_result(observation):
    execution = N / 'source-execution.json'
    if not execution.exists():
        exit_record = observation['processes']['source'].get('exit')
        if exit_record is not None:
            assert exit_record['exit_code'] == 0, 'source failed; no label collection'
        return False
    result = read(execution)
    exit_record = read(N / 'source-job/pipeline-process-exit.json')
    assert result['exit_code'] == exit_record['exit_code'] == 0
    assert exit_record['cleanup']['clean'] and not exit_record['cleanup']['remaining_members']
    assert result['process_exit_sha256'] == sha(N / 'source-job/pipeline-process-exit.json')
    assert result['completion_sha256'] == sha(N / 'natural/completion-verification.json')
    P.C.source_ready(COLLECTOR)
    return True


def main():
    reg = registered()
    if sys.argv[1:] == ['--check']:
        assert not (ROOT / 'study-started.json').exists()
        print({'status': 'registered_without_launch', 'scope': 'simulator_only'})
        return
    assert not sys.argv[1:]
    write(ROOT / 'study-started.json', {'started_at': datetime.now(timezone.utc).isoformat(),
        'pid': os.getpid(), 'command': sys.argv, 'registration_sha256': sha(ROOT / 'study-registration.json'),
        'source_is_owned_by_existing_wrapper': True})

    def interrupted(signum, frame):
        raise InterruptedError('study received signal ' + str(signum))

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        while True:
            schedule = read(N / 'observation-schedule.json')
            assert schedule['status'] == 'running'
            due = datetime.fromisoformat(schedule['next_observation_at'])
            status('waiting_for_source', next_observation_at=due.isoformat())
            # This background process sleeps; it does not inspect job state between observations.
            time.sleep(max(0, (due - datetime.now(timezone.utc)).total_seconds()) + .1)
            subprocess.run([sys.executable, str(N / 'observe.py')], check=True, stdout=subprocess.DEVNULL)
            schedule = read(N / 'observation-schedule.json')
            observation = read(Path(schedule['last_observation']))
            if source_result(observation):
                schedule['status'] = 'complete'
                schedule['completion_verified_at'] = datetime.now(timezone.utc).isoformat()
                (N / 'observation-schedule.json').write_text(json.dumps(schedule, indent=2) + '\n')
                break
            assert datetime.now(timezone.utc) < datetime.fromisoformat(reg['source_wait_deadline']), 'source completion deadline elapsed'
        registered()
        status('collecting_joint_continuations')
        assert P.main() == 0
        registered()
        P.C.proof(COLLECTOR)
        sys.path.insert(0, str(ROOT))
        spec = importlib.util.spec_from_file_location('e128_training_execution', ROOT / 'run_training_pipeline.py')
        training = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(training)
        status('training_and_development')
        training.run()
        result = read(ROOT / 'training-execution.json')
        assert result['status'] == 'complete' and result['evidence_scope'] == 'simulator_only'
        write(ROOT / 'study-completion.json', {'status': 'complete', 'evidence_scope': 'simulator_only',
            'selected_arm': result['selected_arm'], 'training_execution_sha256': sha(ROOT / 'training-execution.json'),
            'unseen_acceptance_games': 0, 'original_game_executions': 0})
        status('complete', selected_arm=result['selected_arm'])
    except BaseException:
        write(ROOT / 'study-error.json', {'error': traceback.format_exc(),
            'at': datetime.now(timezone.utc).isoformat()})
        status('stopped_with_error')
        raise


if __name__ == '__main__':
    main()
