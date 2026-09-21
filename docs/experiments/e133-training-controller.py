"""Launch the frozen E133 training entry after complete data admission."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import traceback

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (ROOT / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def main():
    try:
        if not all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1, 2)):
            raise ValueError('training standard streams must be durable files')
        plan = json.loads((ROOT / 'registration.json').read_text())
        if sha(__file__) != plan['controller_sha256']:
            raise ValueError('training controller changed')
        for path, expected in plan['hashes'].items():
            if sha(path) != expected:
                raise ValueError('training launch input changed: ' + path)
        study = Path(plan['study'])
        runner = Path(plan['runner'])
        sys.path.insert(0, str(runner.parent))
        spec = importlib.util.spec_from_file_location('heart_early_card_experiment', runner)
        experiment = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = experiment
        spec.loader.exec_module(experiment)
        write('started.json', {'controller_pid': os.getpid(),
                              'at': datetime.now(timezone.utc).isoformat()})
        experiment.run(study)
        result = experiment.read(study / 'training-execution-completion.json')
        if result['status'] != 'complete':
            raise ValueError('training completion is missing')
        outcome = {'status': 'complete', 'exit_code': 0, 'selected': result['selected'],
                   'training_execution_completion_sha256':
                       sha(study / 'training-execution-completion.json')}
    except BaseException:
        outcome = {'status': 'stopped_with_error', 'exit_code': 1,
                   'error': traceback.format_exc()}
        traceback.print_exc()
    outcome['finished_at'] = datetime.now(timezone.utc).isoformat()
    write('exit.json', outcome)
    return outcome['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
