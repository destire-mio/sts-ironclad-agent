"""Owned-process controls only; no real source games, labels or model fitting."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time

import run_pipeline as P

ROOT = Path(__file__).resolve().parent
PROBE = ROOT / 'launcher-probe'


def fixture(root, mode):
    root.mkdir()
    script = root / 'fixture.py'
    script.write_text('''from pathlib import Path
import json,os,signal,subprocess,sys,time
p=Path(__file__).resolve().parent
mode=sys.argv[1]
if mode=='normal':
    (p/'normal-result.json').write_text(json.dumps({'value':17}))
    raise SystemExit(0)
if mode=='leaf':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (p/'leaf-ready').write_text(str(os.getpid()))
    time.sleep(60)
    raise SystemExit(0)
leaf=subprocess.Popen([sys.executable,__file__,'leaf'])
(p/'leaf-pid.json').write_text(json.dumps({'pid':leaf.pid,'group':os.getpgrp()}))
deadline=time.monotonic()+5
while not (p/'leaf-ready').exists():
    assert time.monotonic()<deadline
    time.sleep(.02)
if mode=='fault':raise SystemExit(7)
time.sleep(60)
''')
    return [sys.executable, str(script), mode]


def wait_file(path, child):
    deadline = time.monotonic() + 10
    while not path.exists():
        assert child.poll() is None and time.monotonic() < deadline
        time.sleep(.05)


def main():
    assert not PROBE.exists()
    assert not any((ROOT / name).exists() for name in ('pipeline-process.json', 'pipeline.log', 'execution-started.json', 'relic-source', 'joint'))
    try:
        P.main()
    except FileNotFoundError as error:
        assert Path(error.filename).name == 'completion-verification.json'
    else:
        raise AssertionError('incomplete source admitted to launcher')
    assert not any((ROOT / name).exists() for name in ('pipeline-process.json', 'pipeline.log', 'execution-started.json', 'relic-source', 'joint'))
    PROBE.mkdir()
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    cases = []
    try:
        for mode, expected in [('normal', 0), ('fault', 7), ('timeout', 124)]:
            root = PROBE / mode
            command = fixture(root, mode)
            result = P.run_owned(root, command, dict(os.environ), 2 if mode == 'timeout' else 10, 'software-probe')
            assert result['exit_code'] == expected, result
            assert result['cleanup']['clean'] and not P.members(result['cleanup']['process_group'])
            assert sentinel.poll() is None, 'unrelated job was affected'
            if mode == 'normal':
                assert P.C.read(root / 'normal-result.json') == {'value': 17}
            else:
                assert (root / 'leaf-ready').exists(), 'descendant fault scenario was not reached'
            cases.append({'case': mode, 'exit_code': expected, 'cleanup': True, 'unrelated_job_alive': True})
        root = PROBE / 'interrupted'
        command = fixture(root, 'timeout')
        invoke = root / 'invoke.py'
        invoke.write_text('import sys,os,json\nfrom pathlib import Path\n'
            f'sys.path.insert(0,{str(ROOT)!r})\nimport run_pipeline as P\n'
            f'r=P.run_owned(Path({str(root)!r}),{command!r},dict(os.environ),30,"software-probe")\n'
            'raise SystemExit(r["exit_code"])\n')
        with (root / 'wrapper.log').open('x') as log:
            child = subprocess.Popen([sys.executable, str(invoke)], stdout=log, stderr=subprocess.STDOUT)
            try:
                wait_file(root / 'leaf-ready', child)
                child.send_signal(signal.SIGTERM)
                assert child.wait(timeout=10) == 143
                result = P.C.read(root / 'pipeline-process-exit.json')
                assert result['requested_signal'] == signal.SIGTERM
                assert result['cleanup']['clean'] and not P.members(result['cleanup']['process_group'])
                assert sentinel.poll() is None
                cases.append({'case': 'wrapper_SIGTERM', 'exit_code': 143, 'cleanup': True, 'unrelated_job_alive': True})
            finally:
                if child.poll() is None:
                    child.kill(); child.wait()
                metadata = root / 'pipeline-process.json'
                if metadata.exists():
                    group = P.C.read(metadata)['process_group']
                    if P.members(group):
                        os.killpg(group, signal.SIGKILL)
    finally:
        sentinel.terminate(); sentinel.wait(timeout=5)
    P.C.write(PROBE / 'completion-verification.json', {'status': 'passed', 'cases': cases,
        'incomplete_source_rejected_before_launch': True, 'collector_registration_sha256': P.C.sha(ROOT / 'registration.json'),
        'launcher_sha256': P.C.sha(ROOT / 'run_pipeline.py'), 'checker_sha256': P.C.sha(__file__),
        'new_mcts_calls': 0, 'new_labels': 0, 'optimizer_updates': 0,
        'hashes': {str(p.relative_to(PROBE)): P.C.sha(p) for p in sorted(PROBE.rglob('*')) if p.is_file()}})
    print({'status': 'passed', 'cases': cases})


if __name__ == '__main__':
    main()
