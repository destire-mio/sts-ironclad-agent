"""Execute the frozen E119 recipe once, with owned workers and native cleanup."""
from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import os
import sys
import time
import traceback

import scale_training as T
import scale_development as G

ROOT = T.ROOT
JOBS = ROOT / 'execution'
A = ROOT.parents[2] / 'ironclad-alignment'
read, write, sha = T.read, T.write, T.sha


def registration():
    reg = read(ROOT / 'training-execution-registration.json')
    for path, expected in reg['hashes'].items():
        assert sha(path) == expected, path
    resolved = reg['resolved_stateless_bomb_helper']
    assert sha(resolved['path']) == resolved['sha256'] == sha(ROOT / 'bomb_instances.py')
    for root in (ROOT, T.COLLECTOR, T.SOURCE):
        assert not (root / 'source-closed.json').exists(), 'closed inputs: ' + str(root)
    probe = read(T.COLLECTOR / 'launcher-probe/completion-verification.json')
    assert probe['status'] == 'passed'
    assert probe['launcher_sha256'] == sha(T.COLLECTOR / 'run_pipeline.py')
    assert probe['checker_sha256'] == sha(T.COLLECTOR / 'check-launcher.py')
    assert probe['collector_registration_sha256'] == sha(T.COLLECTOR / 'registration.json')
    assert {r['case'] for r in probe['cases']} == {'normal', 'fault', 'timeout', 'wrapper_SIGTERM'}
    assert all(r['cleanup'] and r['unrelated_job_alive'] for r in probe['cases'])
    for name, expected in probe['hashes'].items():
        assert sha(T.COLLECTOR / 'launcher-probe' / name) == expected, name
    G.registered()
    return reg


def admit():
    reg = registration()
    # All input and parity checks precede any formal outputs or child process.
    T.load_inputs()
    for path in (JOBS, T.OUTPUT, ROOT / 'original-candidates', ROOT / 'training-execution.json'):
        assert not path.exists(), 'preserve previous execution: ' + str(path)
    return reg


def owned_module():
    sys.path.insert(0, str(T.COLLECTOR))
    spec = importlib.util.spec_from_file_location('e118_owned_training_launcher', T.COLLECTOR / 'run_pipeline.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cleanup_originals():
    """Only this study's arm/seed instances can be stopped."""
    sys.path.insert(0, str(A / 'oracle'))
    import run as native
    rows = []
    for arm in G.ARMS:
        base = ROOT / 'original-candidates' / arm / 'original'
        for instance in sorted(base.glob('*/instance')):
            # Resolve ownership before handing any path to the native tool.
            assert instance.resolve().is_relative_to(base.resolve())
            if not (instance / 'last-launch.json').exists():
                continue
            native.stop(instance)
            if native.instance_processes(instance):
                native.stop(instance, force=True)
            rows.append({'instance': str(instance), 'remaining': native.instance_processes(instance)})
    assert all(not row['remaining'] for row in rows), 'owned native process survived'
    return rows


def emit_status(value):
    path = JOBS / 'status.json'
    temp = path.with_suffix('.tmp')
    import json
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def run():
    reg = admit()
    entry = read(ROOT / 'training-execution-entry-verification.json')
    assert entry['status'] == 'passed'
    assert entry['incomplete_inputs_rejected_before_execution']
    assert entry['registration_sha256'] == sha(ROOT / 'training-execution-registration.json')
    assert entry['launcher_sha256'] == sha(__file__)
    assert entry['checker_sha256'] == sha(ROOT / 'check-training-execution.py')
    jobs, transitions = [], []
    owner = owned_module()
    JOBS.mkdir()
    write(JOBS / 'started.json', {'created_at': datetime.now(timezone.utc).isoformat(),
        'controller_pid': os.getpid(), 'registration_sha256': sha(ROOT / 'training-execution-registration.json'),
        'input_proofs_sha256': {str(path): sha(path) for path in (
            T.SOURCE / 'natural/completion-verification.json',
            T.COLLECTOR / 'completion-verification.json',
            T.COLLECTOR / 'relic-source/label-verification.json',
            T.NEW / 'label-verification.json',
            Path(read(T.COLLECTOR / 'protocol.json')['parity_root']) / 'completion-verification.json')},
        'retries': 0, 'total_seconds': reg['total_seconds']})
    deadline = time.monotonic() + reg['total_seconds']
    environment = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')

    def stage(name, command, allowance):
        remaining = deadline - time.monotonic()
        assert remaining > 0, 'training execution deadline reached'
        directory = JOBS / name
        directory.mkdir()
        emit_status({'stage': name, 'completed_stages': [row['name'] for row in jobs],
                     'controller_pid': os.getpid()})
        outcome = owner.run_owned(directory, [sys.executable, '-u', *command], environment,
            min(allowance, remaining), sha(ROOT / 'training-execution-registration.json'))
        jobs.append({'name': name, 'exit_code': outcome['exit_code'],
            'process_exit_sha256': sha(directory / 'pipeline-process-exit.json')})
        assert outcome['exit_code'] == 0 and outcome['cleanup']['clean'], (name, outcome)
        registration()

    try:
        stage('fit', [str(ROOT / 'scale_training.py'), 'train'], reg['fit_seconds'])
        stage('verify', [str(ROOT / 'scale_verify.py'), 'verify'], reg['verification_wrapper_seconds'])
        _, learning = G.learning_ready()
        for arm in G.ARMS:
            if not learning['arms'][arm]['passed']:
                transitions.append({'arm': arm, 'outcome': 'rejected_at_label_holdout',
                                    'natural_games_started': False, 'original_started': False})
                continue
            stage(arm + '-natural', [str(ROOT / 'scale_development.py'), 'natural', '--arm', arm],
                  reg['natural_wrapper_seconds_per_arm'])
            _, _, natural = G.natural_ready(arm)
            if not natural['passed']:
                transitions.append({'arm': arm, 'outcome': 'rejected_at_natural_development',
                                    'natural_games_started': True, 'original_started': False})
                continue
            original = G.prepare_original(arm)
            try:
                stage(arm + '-original', [str(ROOT / 'candidate_original.py'), '--root', str(original)],
                      reg['original_wrapper_seconds_per_arm'])
            finally:
                write(JOBS / (arm + '-native-cleanup.json'), {'instances': cleanup_originals()})
            transitions.append({'arm': arm, 'outcome': 'original_command_complete_pending_final_admission',
                                'natural_games_started': True, 'original_started': True})
        stage('finalize', [str(ROOT / 'scale_development.py'), 'finalize'], reg['finalize_seconds'])
        complete = T.proof(T.OUTPUT, 'development-completion.json')
        decision = read(T.OUTPUT / 'development-decision.json')
        assert decision['status'] == 'complete' and decision['selected_arm'] == complete['selected_arm']
        assert decision['production_adoption'] is False and decision['unseen_acceptance_games'] == 0
        result = {'status': 'complete',
            'jobs': jobs, 'transitions': transitions,
            'registration_sha256': sha(ROOT / 'training-execution-registration.json'),
            'development_completion_sha256': sha(T.OUTPUT / 'development-completion.json'),
            'selected_arm': decision['selected_arm'], 'production_adoption': False, 'unseen_acceptance_games': 0,
            'limits': 'Execution of the registered development study. No automatic adoption or final acceptance.'}
    except BaseException:
        write(JOBS / 'error.json', {'error': traceback.format_exc(), 'jobs': jobs, 'transitions': transitions,
            'created_at': datetime.now(timezone.utc).isoformat()})
        emit_status({'status': 'stopped_with_error', 'completed_stages': [row['name'] for row in jobs]})
        raise
    finally:
        try:
            write(JOBS / 'native-cleanup.json', {'instances': cleanup_originals()})
        except BaseException:
            write(JOBS / 'native-cleanup-error.json', {'error': traceback.format_exc()})
            emit_status({'status': 'stopped_with_cleanup_error'})
            raise
    result['native_cleanup_sha256'] = sha(JOBS / 'native-cleanup.json')
    result['execution_started_sha256'] = sha(JOBS / 'started.json')
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    write(ROOT / 'training-execution.json', result)
    emit_status({'status': 'complete', 'selected_arm': result['selected_arm']})


if __name__ == '__main__':
    if sys.argv[1:] == ['--check']:
        admit()
        print({'status': 'admitted_without_launch'})
    else:
        assert not sys.argv[1:]
        run()
