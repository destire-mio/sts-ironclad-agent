"""Own the bounded joint-encoder training comparison."""
import argparse
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import traceback


def main(root, owned):
    sys.path.insert(0, str(root / 'program'))
    import heart_joint_encoder as L
    E = L.E
    plan = L.registered(root)
    control = root / 'control'
    if not owned:
        assert E.read(root / 'preflight.json')['status'] == 'passed'
        control.mkdir()
        launcher = Path(plan['owned_launcher'])
        E.write(control / 'registration.json', dict(owned_launcher=str(launcher),
            hashes={str(p): E.sha(p) for p in (Path(__file__), launcher, launcher.with_name('run_collections.py'), root / 'registration.json', root / 'preflight.json')}))
        with (control / 'controller.log').open('xb') as log:
            child = subprocess.Popen([sys.executable, '-u', __file__, '--study', str(root), '--owned'],
                cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'))
        launch = dict(status='launched', pid=child.pid, at=datetime.now(timezone.utc).isoformat(),
            registration_sha256=E.sha(root / 'registration.json'))
        E.write(control / 'launch.json', launch)
        print(launch)
        return 0
    try:
        registration = E.read(control / 'registration.json')
        for path, digest in registration['hashes'].items():
            assert E.sha(path) == digest
        launcher = Path(registration['owned_launcher'])
        sys.path.insert(0, str(launcher.parent))
        spec = importlib.util.spec_from_file_location('e182_owned', launcher)
        owner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(owner)
        assert Path(owner.C.__file__).resolve() == launcher.parent / 'run_collections.py'
        output = root / 'training-execution'
        output.mkdir()
        E.write(control / 'started.json', dict(pid=os.getpid(), at=datetime.now(timezone.utc).isoformat()))
        result = owner.run_owned(output, [sys.executable, '-u', str(root / 'program/heart_joint_encoder.py'), '--study', str(root)],
            dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'),
            plan['timeout_seconds'] + 120, E.sha(root / 'registration.json'))
        assert result['exit_code'] == 0 and result['cleanup']['clean']
        E.proof(root / 'learning', 'completion.json')
        end = dict(status='complete', phase='training', exit_code=0,
            owned_exit_sha256=E.sha(output / 'pipeline-process-exit.json'), completion_sha256=E.sha(root / 'learning/completion.json'))
    except BaseException:
        end = dict(status='stopped_with_error', phase='training', exit_code=1, error=traceback.format_exc())
        traceback.print_exc()
    end['finished_at'] = datetime.now(timezone.utc).isoformat()
    E.write(control / 'exit.json', end)
    return end['exit_code']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--owned', action='store_true')
    args = parser.parse_args()
    raise SystemExit(main(args.study.resolve(), args.owned))
