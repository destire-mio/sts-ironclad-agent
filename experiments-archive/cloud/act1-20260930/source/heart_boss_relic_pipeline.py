#!/usr/bin/env python3
"""Bounded sequential execution of the registered E55 -> E56 experiment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temp.replace(path)


def run(root, pipeline, repository):
    child = None
    def stop(signum, frame):
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
        raise SystemExit(128 + signum)
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, stop)
    protocol = read(root / 'protocol.json')
    source = Path(protocol['source'])
    hashes = {str(p): sha(p) for p in (root/'protocol.json', root/'registered-runner.py',
        root/'registered-model.py', root/'registered-audit.py', root/'run_development.py', root/'preflight-contract.json')}
    write(pipeline/'inputs.json', {'hashes': hashes, 'source': str(source), 'source_manifest_sha256': protocol['source_manifest_sha256']})
    def stage(name, script, args, runtime, bootstrap=False):
        nonlocal child
        for name_, expected in hashes.items(): assert sha(Path(name_)) == expected
        write(pipeline/'status.json', {'stage': name, 'status': 'running', 'started_at': time.time()})
        env = {**os.environ, 'HEART_BRANCH_RUNTIME': str(runtime), 'PYTHONPATH': str(repository/'agent') if bootstrap else str(root),
            'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
        with (pipeline/f'{name}.log').open('x') as log:
            child = subprocess.Popen([sys.executable, str(script), *args], cwd=root, env=env,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            code = child.wait()
        assert code == 0, f'{name} failed with {code}; see its retained log'
    try:
        write(pipeline/'status.json', {'stage': 'waiting_for_source_verification', 'status': 'running'})
        deadline = time.monotonic() + 12000
        while not (source/'completion-verification.json').exists():
            assert time.monotonic() < deadline, 'source verification not available before the waiting guard'
            if (source/'collection-accounting.json').exists():
                accounting = read(source/'collection-accounting.json')
                assert not accounting['faults'] and accounting['returned'] == accounting['requested'], 'source contains faults; do not collect new labels'
            time.sleep(10)
        proof = read(source/'completion-verification.json')
        assert proof['status'] == 'complete' and proof['zero_faults']
        for name, expected in proof['hashes'].items(): assert sha(source/name) == expected
        stage('prepare', root/'registered-runner.py', ['prepare','--root',str(root)], source, True)
        stage('collect', root/'run_boss_bandit.py', ['collect','--root',str(root)], root)
        stage('audit_labels', root/'verify_boss_labels.py', ['--root',str(root)], root)
        stage('train', root/'run_boss_bandit.py', ['train','--root',str(root)], root)
        if not (root/'training-report.json').exists():
            assert read(root/'decision.json')['stage'] == 'coverage'
            write(pipeline/'status.json', {'status': 'complete', 'stage': 'coverage_rejected', 'decision_sha256': sha(root/'decision.json')})
            return
        stage('verify_learning', root/'run_development.py', ['verify-learning','--root',str(root)], root)
        if not read(root/'learning-verification.json')['label_holdout_gate_passed']:
            write(pipeline/'status.json', {'status': 'complete', 'stage': 'label_holdout_rejected', 'decision_sha256': sha(root/'decision.json')})
            return
        stage('natural_development', root/'run_development.py', ['develop','--root',str(root)], root)
        decision = read(root/'decision.json')
        write(pipeline/'status.json', {'status': 'complete', 'stage': 'ready_for_fresh_confirmation' if decision['passed'] else 'development_rejected',
            'decision_sha256': sha(root/'decision.json')})
    except Exception:
        write(pipeline/'status.json', {'status': 'execution_review_required', 'error': traceback.format_exc()})
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--pipeline', type=Path, required=True)
    p.add_argument('--repository', type=Path, required=True)
    a = p.parse_args()
    run(a.root.resolve(), a.pipeline.resolve(), a.repository.resolve())
