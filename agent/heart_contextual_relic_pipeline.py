#!/usr/bin/env python3
"""Run the registered E69 stages after source and parity audits finish."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def run(root, repository):
    plan = read(root / 'protocol.json')
    source, parity = Path(plan['source']), Path(plan['parity_root'])
    for name, expected in read(root / 'registration.json')['hashes'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    status = root / 'pipeline-status.json'
    try:
        write(status, {'stage': 'waiting_for_source_and_parity', 'pid': os.getpid()})
        deadline = time.monotonic() + 10800
        while not all((folder / 'completion-verification.json').exists() for folder in (source, parity)):
            accounting = source / 'collection-accounting.json'
            if accounting.exists():
                assert not read(accounting)['faults'], 'source collection has null/fault labels'
            if time.monotonic() >= deadline:
                raise TimeoutError('prerequisite audits did not finish within three hours')
            time.sleep(15)
        phases = [('prepare', repository / 'agent/heart_contextual_relic_learning.py', 'prepare'),
                  ('collect', root / 'run_contextual_learning.py', 'collect'),
                  ('audit-labels', root / 'verify_boss_labels.py', None),
                  ('train', root / 'run_contextual_learning.py', 'train'),
                  ('verify-learning', root / 'run_development.py', 'verify-learning'),
                  ('develop', root / 'run_development.py', 'develop')]
        for phase, script, command in phases:
            if phase == 'prepare':
                # Execute the registered source, importing its frozen behavior
                # dependencies from the repository before the run is prepared.
                script = root / 'registered-runner.py'
            if phase == 'verify-learning' and (root / 'decision.json').exists():
                decision = read(root / 'decision.json')
                if decision.get('stage') == 'coverage' and not decision['passed']:
                    write(status, {'stage': 'complete', 'decision': decision})
                    return
            env = dict(os.environ, HEART_BRANCH_RUNTIME=str(source if phase == 'prepare' else root),
                       PYTHONPATH=str(repository / 'agent'))
            write(status, {'stage': phase, 'pid': os.getpid()})
            args = [sys.executable, str(script)] + ([command] if command else []) + ['--root', str(root)]
            with (root / (phase + '.log')).open('x') as stream:
                subprocess.run(args, cwd=repository, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
        write(status, {'stage': 'complete', 'decision': read(root / 'decision.json')})
    except Exception:
        write(status, {'stage': 'failed', 'error': traceback.format_exc(), 'pid': os.getpid()})
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--repository', type=Path, required=True)
    a = p.parse_args()
    run(a.root.resolve(), a.repository.resolve())
