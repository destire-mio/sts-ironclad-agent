#!/usr/bin/env python3
"""Execute the frozen E37 exposure comparison with stage logs and child cleanup."""
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


def main():
    global child
    assert json.loads((root / 'plan.json').read_text())['experiment'] == 'E37'
    with (root / 'execution-manifest.json').open('x') as stream:
        json.dump({'pipeline_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'protocol_sha256': hashlib.sha256((root / 'plan.json').read_bytes()).hexdigest()}, stream, indent=2)
    for stage in ('train', 'diagnose', 'evaluate', 'verify', 'finish'):
        with (root / (stage + '.log')).open('x') as log:
            child = subprocess.Popen([sys.executable, str(root / 'run_suffix_exposure.py'), stage, '--root', str(root)],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            write(root / 'pipeline-status.json', {'status': 'running', 'stage': stage,
                'controller_pid': os.getpid(), 'child_pid': child.pid})
            code = child.wait()
            child = None
            if code:
                raise RuntimeError(f'{stage} exited {code}; inspect its saved log')
    write(root / 'pipeline-status.json', {'status': 'complete', 'stage': 'E37_development_complete'})


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
