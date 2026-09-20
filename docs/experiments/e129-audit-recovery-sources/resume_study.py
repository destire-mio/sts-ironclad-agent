"""Finish source audits, then enter the unchanged E127/E128 simulator recipes."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
COLLECTOR = ROOT.parent / 'heart-e121-simulator-joint-labels-20260920-01'
TRAINING = ROOT.parent / 'heart-e121-simulator-training-20260920-01'
sys.path.insert(0, str(COLLECTOR))
import run_pipeline as P
read, write, sha = P.C.read, P.C.write, P.C.sha


def registered():
    reg = read(ROOT / 'registration.json')
    for path, expected in reg['hashes'].items():
        assert sha(path) == expected, path
    assert reg['observer_interval_seconds'] == 1200
    assert reg['evidence_scope'] == 'simulator_only'
    assert read(ROOT / 'entry-verification.json')['status'] == 'passed'
    probe = read(COLLECTOR / 'launcher-probe/completion-verification.json')
    assert probe['status'] == 'passed' and probe['launcher_sha256'] == sha(P.__file__)
    assert {case['case'] for case in probe['cases']} == {'normal', 'fault', 'timeout', 'wrapper_SIGTERM'}
    assert all(case['cleanup'] and case['unrelated_job_alive'] for case in probe['cases'])
    for name, expected in probe['hashes'].items():
        assert sha(COLLECTOR / 'launcher-probe' / name) == expected, name
    return reg


def status(stage, **extra):
    temp = ROOT / 'study-status.tmp'
    temp.write_text(json.dumps({'stage': stage, 'controller_pid': os.getpid(),
        'updated_at': datetime.now(timezone.utc).isoformat(), **extra}, indent=2) + '\n')
    temp.replace(ROOT / 'study-status.json')


def main():
    reg = registered()
    write(ROOT / 'study-started.json', {'started_at': datetime.now(timezone.utc).isoformat(),
        'controller_pid': os.getpid(), 'registration_sha256': sha(ROOT / 'registration.json'),
        'evidence_scope': 'simulator_only'})
    try:
        job = ROOT / 'audit-job'
        job.mkdir()
        status('completing_saved_source_audits')
        environment = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        result = P.run_owned(job, [sys.executable, '-u', str(ROOT / 'recover_audit.py'), 'run'],
            environment, reg['wrapper_seconds'], sha(ROOT / 'registration.json'))
        assert result['exit_code'] == 0 and result['cleanup']['clean'], result
        P.C.source_ready(COLLECTOR)
        write(ROOT / 'source-admission.json', {'status': 'complete',
            'source_completion_sha256': sha(Path(reg['natural_source']) / 'completion-verification.json'),
            'audit_exit_sha256': sha(job / 'pipeline-process-exit.json'),
            'original_source_exit_code': 1, 'evidence_scope': 'simulator_only'})
        registered()
        status('collecting_joint_continuations')
        assert P.main() == 0
        registered()
        P.C.proof(COLLECTOR)
        sys.path.insert(0, str(TRAINING))
        spec = importlib.util.spec_from_file_location('e128_resumed_execution', TRAINING / 'run_training_pipeline.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        status('training_and_development')
        module.run()
        execution = read(TRAINING / 'training-execution.json')
        assert execution['status'] == 'complete' and execution['evidence_scope'] == 'simulator_only'
        write(ROOT / 'study-completion.json', {'status': 'complete', 'evidence_scope': 'simulator_only',
            'training_execution_sha256': sha(TRAINING / 'training-execution.json'),
            'selected_arm': execution['selected_arm'], 'unseen_acceptance_games': 0,
            'original_game_executions': 0})
        status('complete', selected_arm=execution['selected_arm'])
    except BaseException:
        write(ROOT / 'study-error.json', {'error': traceback.format_exc(),
            'at': datetime.now(timezone.utc).isoformat()})
        status('stopped_with_error')
        raise


if __name__ == '__main__':
    main()
