"""Launch one bounded owned phase; natural evaluation needs root learning review."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


def main(root, phase, owned):
    sys.path.insert(0, str(root / 'program'))
    import heart_expected_improvement as I
    E = I.E
    plan = I.registered(root)
    control = root / (phase + '-control')
    if not owned:
        preflight = E.read(root / 'preflight.json')
        assert preflight['status'] == 'passed' and preflight['runner_sha256'] == E.sha(I.__file__)
        if phase == 'evaluate':
            review = E.read(root / 'training-review.json')
            assert review['status'] == 'complete_reviewed' and review['eligible_for_natural_evaluation']
        control.mkdir()
        launcher = Path(E.read(Path(plan['preceding_study']) / 'control/registration.json')['owned_launcher'])
        E.write(control / 'registration.json', dict(phase=phase, owned_launcher=str(launcher),
            hashes={str(p): E.sha(p) for p in (Path(__file__), launcher, launcher.with_name('run_collections.py'), root / 'registration.json')}))
        with (control / 'controller.log').open('xb') as log:
            child = subprocess.Popen([sys.executable, '-u', __file__, '--study', str(root), '--phase', phase, '--owned'],
                cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'))
        launched = dict(status='launched', phase=phase, pid=child.pid, at=datetime.now(timezone.utc).isoformat(),
            registration_sha256=E.sha(root / 'registration.json'))
        E.write(control / 'launch.json', launched)
        print(json.dumps(launched))
        return 0
    try:
        registered = E.read(control / 'registration.json')
        assert registered['phase'] == phase
        for path, digest in registered['hashes'].items():
            assert E.sha(path) == digest
        launcher = Path(registered['owned_launcher'])
        sys.path.insert(0, str(launcher.parent))
        spec = importlib.util.spec_from_file_location('e160_owned', launcher)
        owner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(owner)
        assert Path(owner.C.__file__).resolve() == launcher.parent / 'run_collections.py'
        output = root / (phase + '-execution')
        output.mkdir()
        budget = plan['training_timeout_seconds'] if phase == 'train' else plan['evaluation_timeout_seconds'] + 120
        E.write(control / 'started.json', dict(pid=os.getpid(), at=datetime.now(timezone.utc).isoformat(), phase=phase))
        outcome = owner.run_owned(output, [sys.executable, '-u', str(root / 'program/heart_expected_improvement.py'), phase, '--study', str(root)],
            dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'), budget, E.sha(root / 'registration.json'))
        assert outcome['exit_code'] == 0 and outcome['cleanup']['clean']
        proof = root / ('learning/completion.json' if phase == 'train' else 'evaluation/completion-verification.json')
        assert E.read(proof)['status'] == 'complete'
        result = dict(status=phase + '_complete', exit_code=0, phase=phase,
            owned_exit_sha256=E.sha(output / 'pipeline-process-exit.json'), completion_sha256=E.sha(proof))
    except BaseException:
        result = dict(status='stopped_with_error', exit_code=1, phase=phase, error=traceback.format_exc())
        traceback.print_exc()
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    E.write(control / 'exit.json', result)
    return result['exit_code']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--phase', choices=('train', 'evaluate'), required=True)
    parser.add_argument('--owned', action='store_true')
    args = parser.parse_args()
    raise SystemExit(main(args.study.resolve(), args.phase, args.owned))
