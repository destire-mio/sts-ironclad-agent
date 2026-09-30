#!/usr/bin/env python3
"""Run one frozen E36 protocol; preserve each completed stage and its logs."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

root = Path(__file__).resolve().parent
child = None


def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def stop(signum, frame):
    raise KeyboardInterrupt


def run(name, script, args):
    global child
    with (root / (name + '.log')).open('x') as log:
        child = subprocess.Popen([sys.executable, str(root / script), *args],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        write(root / 'pipeline-status.json', {'status': 'running', 'stage': name,
            'controller_pid': os.getpid(), 'child_pid': child.pid})
        code = child.wait()
        child = None
        if code:
            raise RuntimeError(f'{name} exited {code}; inspect the saved log')


def main():
    plan = json.loads((root / 'plan.json').read_text())
    assert plan['experiment'] == 'E36'
    with (root / 'execution-manifest.json').open('x') as stream:
        json.dump({'pipeline_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'protocol_sha256': hashlib.sha256((root / 'plan.json').read_bytes()).hexdigest()}, stream, indent=2)
    run('objective_tests', 'objective_tests.py', [])
    for iteration in range(plan['iterations']):
        tail = ['--root', str(root), '--iteration', str(iteration)]
        run(f'iteration_{iteration}_collect', 'run_suffix_policy.py', ['collect', *tail])
        run(f'iteration_{iteration}_audit', 'verify_suffix_policy.py', ['labels', *tail])
        if iteration == 0:
            report = json.loads((root / 'iterations/0/collection-report.json').read_text())
            fit = report['coverage']['fit']
            passed = (fit['mixed_families'] >= plan['coverage']['initial_minimum_mixed_fit_families']
                and fit['rescued_greedy_failure_families'] >= plan['coverage']['initial_minimum_rescued_fit_families'])
            write(root / 'coverage-decision.json', {'passed': passed, 'fit': fit, 'thresholds': plan['coverage']})
            if not passed:
                write(root / 'decision.json', {'experiment': 'E36', 'status': 'complete',
                    'reason': 'initial mixed/rescued fit-family coverage gate failed', 'coverage': fit,
                    'optimizer_updates': 0, 'selected_for_fresh_acceptance': None, 'new_acceptance_seeds': 0})
                write(root / 'pipeline-status.json', {'status': 'complete', 'stage': 'coverage_gate_failed'})
                return
        run(f'iteration_{iteration}_train', 'run_suffix_policy.py', ['train', *tail])
        if json.loads((root / f'iterations/{iteration}/training-report.json').read_text()).get('stopped_for_low_fit_signal'):
            break
    for stage in ('complete-training', 'diagnose', 'evaluate'):
        run(stage, 'run_suffix_policy.py', [stage, '--root', str(root)])
    run('evaluation_audit', 'verify_suffix_policy.py', ['evaluation', '--root', str(root)])
    run('finish', 'run_suffix_policy.py', ['finish', '--root', str(root)])
    write(root / 'pipeline-status.json', {'status': 'complete', 'stage': 'E36_development_complete'})


if __name__ == '__main__':
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        main()
    except BaseException as error:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait()
        write(root / 'pipeline-status.json', {'status': 'error', 'stage': 'stopped_for_review', 'error': repr(error)})
        raise
