#!/usr/bin/env python3
"""Run the frozen two-arm trajectory preference study without checkpoint selection."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

root = Path(__file__).resolve().parent
child = None


def write(value):
    path = root / 'pipeline-status.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2)+'\n')
    temp.replace(path)


def stop(signum, frame):
    raise KeyboardInterrupt


def invoke(arm, stage):
    global child
    with (root / f'{arm}-{stage}.log').open('x') as log:
        child = subprocess.Popen([sys.executable, str(root / arm / 'run_trajectory_preference.py'),
            stage, '--root', str(root / arm if stage != 'select' else root)],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        write({'status': 'running', 'arm': arm, 'stage': stage,
               'controller_pid': os.getpid(), 'child_pid': child.pid})
        code = child.wait()
        child = None
        if code:
            raise RuntimeError(f'{arm} {stage} exited {code}; inspect saved log')


if __name__ == '__main__':
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        # Train both before any new greedy outcome is inspected.
        for arm in ('legacy', 'boss'):
            invoke(arm, 'train')
        for arm in ('legacy', 'boss'):
            for stage in ('diagnose', 'evaluate', 'verify', 'finish'):
                invoke(arm, stage)
        invoke('legacy', 'select')
        write({'status': 'complete', 'stage': 'E41_E42_complete'})
    except BaseException as error:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait()
        write({'status': 'error', 'stage': 'stopped_for_review', 'error': repr(error)})
        raise
