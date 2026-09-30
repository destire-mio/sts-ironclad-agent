"""Resume an unstarted, frozen training recipe after completed collection.

The controller owns a regular log file, so closing a tool's output pipe cannot
abort a later stage. The registered recipe retains its worker cleanup/deadlines.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import traceback


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def registered(root):
    plan = read(root / 'registration.json')
    assert sha(__file__) == plan['runner_sha256'], 'recovery runner changed'
    for path, expected in plan['hashes'].items():
        assert sha(path) == expected, path
    collector = Path(plan['collector'])
    complete = read(collector / 'pipeline-execution-verification.json')
    outcome = read(collector / 'pipeline-process-exit.json')
    assert complete['status'] == 'complete' and complete['cleanup_verified']
    assert complete['process_exit_sha256'] == sha(collector / 'pipeline-process-exit.json')
    assert complete['collection_completion_sha256'] == sha(collector / 'completion-verification.json')
    assert outcome['exit_code'] == 0 and outcome['cleanup']['clean']
    return plan


def training_module(plan):
    study = Path(plan['training_study'])
    sys.path.insert(0, str(study))
    spec = importlib.util.spec_from_file_location('resumed_frozen_training', study / 'run_training_pipeline.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.ROOT).resolve() == study.resolve()
    return module


def check(root):
    assert not (root / 'execution').exists(), 'preserve the recovery attempt'
    plan = registered(root)
    training_module(plan).admit()
    return plan


def detached(command, log_path, cwd):
    # All three standard streams must outlive the interactive launch process.
    with Path(log_path).open('x') as log:
        assert stat.S_ISREG(os.fstat(log.fileno()).st_mode)
        return subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            close_fds=True)


def start(root):
    check(root)
    execution = root / 'execution'
    execution.mkdir()  # Exclusive ownership; concurrent starts cannot both win.
    write(execution / 'admission.json', {'status': 'passed', 'at': now(),
        'registration_sha256': sha(root / 'registration.json'), 'formal_jobs_started': 0})
    command = [sys.executable, '-u', str(Path(__file__).resolve()), '_run', '--root', str(root)]
    child = detached(command, execution / 'controller.log', root)
    launch = {'pid': child.pid, 'process_group': child.pid, 'command': command,
        'started_at': now(), 'registration_sha256': sha(root / 'registration.json'),
        'stdio': 'stdin=/dev/null; stdout and stderr=execution/controller.log'}
    write(execution / 'launch.json', launch)
    return launch


def run(root):
    execution = root / 'execution'
    try:
        assert stat.S_ISREG(os.fstat(1).st_mode), 'controller stdout must be a regular file'
        assert stat.S_ISREG(os.fstat(2).st_mode), 'controller stderr must be a regular file'
        plan = registered(root)
        write(execution / 'started.json', {'controller_pid': os.getpid(), 'at': now(),
            'registration_sha256': sha(root / 'registration.json')})
        training_module(plan).run()
        study = Path(plan['training_study'])
        result = read(study / 'training-execution.json')
        assert result['status'] == 'complete' and result['evidence_scope'] == 'simulator_only'
        outcome = {'exit_code': 0, 'status': 'complete', 'finished_at': now(),
            'training_execution_sha256': sha(study / 'training-execution.json'),
            'selected_arm': result['selected_arm']}
    except BaseException:
        outcome = {'exit_code': 1, 'status': 'stopped_with_error',
            'finished_at': now(), 'error': traceback.format_exc()}
        traceback.print_exc()
    write(execution / 'exit.json', outcome)
    return outcome['exit_code']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('check', 'start', '_run'))
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == '_run':
        raise SystemExit(run(root))
    if args.command == 'check':
        check(root)
        print({'status': 'admitted_without_launch'}, flush=True)
    else:
        print(json.dumps(start(root)), flush=True)
