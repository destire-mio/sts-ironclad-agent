"""Run current contracts and archived-trajectory tests in separate interpreters.

The archived fixtures name a particular native engine. Importing every test in
one interpreter can reuse an already-loaded slaythespire module from another
experiment, even after STS_LIGHTSPEED_BUILD changes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


REPO = Path(__file__).resolve().parents[1]
ARCHIVED = {
    'test_heart_branch_pilot', 'test_heart_branch_training', 'test_heart_floor_gate',
    'test_heart_suffix_objective', 'test_heart_trajectory_preference',
}
BOOTSTRAP = '''
import hashlib, importlib, json, os, pathlib, sys, unittest
sys.path[:0] = [str(pathlib.Path('tests').resolve()), str(pathlib.Path('agent').resolve())]
module = importlib.import_module(sys.argv[1])
native = sys.modules.get('slaythespire')
if native is not None:
    path = pathlib.Path(native.__file__).resolve()
    expected = pathlib.Path(os.environ['TEST_EXPECTED_ENGINE']).resolve()
    assert path.parent == expected, (str(path), str(expected))
    print(json.dumps({'native': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}), flush=True)
unittest.main(module=module, argv=[sys.argv[1], '-v'])
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True, help='current engine for current contracts')
    p.add_argument('--runs', type=Path, default=REPO / 'runs', help='local frozen historical artifacts')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    results = []
    for test in sorted((REPO / 'tests').glob('test_*.py')):
        runtime = a.runs / 'heart-training-set-evaluation-20260915-01'
        build = a.build
        expected_sha = None
        if test.stem in ARCHIVED:
            build = runtime / 'engine'
            expected_sha = '6b66eabe8e7a11a91fbba11d6cbdf0d1247d1e2a2137aa46501b96c436af2ffd'
        elif test.stem in {'test_heart_portal_validation', 'test_heart_success_collect'}:
            build = a.runs / 'heart-total-data-20260915-01/engine'
            expected_sha = '9bcc137222d051ae58d437cf0f5551db807bff2815f78ca604eb189fa0fddfe2'
        elif test.stem == 'test_heart_contextual_relic':
            runtime = a.runs / 'heart-repaired-refresh-20260918-01'
            build = runtime / 'engine'
            expected_sha = '920d2ba364ae1c7dbc7a6bdf210c8f8531b7bcb34bf54604f12b769e82968377'
        modules = list(build.glob('slaythespire*.so'))
        if len(modules) != 1:
            raise RuntimeError(f'exactly one native module is required in {build}')
        digest = hashlib.sha256(modules[0].read_bytes()).hexdigest()
        if expected_sha and digest != expected_sha:
            raise RuntimeError(f'archived engine hash mismatch for {test.stem}')
        env = {**os.environ, 'STS_LIGHTSPEED_BUILD': str(build.resolve()),
               'TEST_EXPECTED_ENGINE': str(build.resolve()),
               'HEART_BRANCH_RUNTIME': str(runtime.resolve()),
               'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
        with (a.output / f'{test.stem}.log').open('w') as log:
            result = subprocess.run([sys.executable, '-c', BOOTSTRAP, test.stem],
                                    cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        results.append({'test_module': test.stem, 'returncode': result.returncode,
                        'engine': str(modules[0].resolve()), 'engine_sha256': digest,
                        'archived_runtime': expected_sha is not None})
        (a.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(test.stem, result.returncode, flush=True)
    return int(any(r['returncode'] for r in results))


if __name__ == '__main__':
    sys.exit(main())
