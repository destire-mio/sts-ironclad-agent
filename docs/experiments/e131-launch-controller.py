"""Durable-log entry for the registered E131 pilot; no recipe modifications."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import traceback


ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(name, value):
    with (ROOT / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def main():
    try:
        assert all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1, 2))
        registration = read(ROOT / 'registration.json')
        assert sha(__file__) == registration['controller_sha256']
        for path, expected in registration['hashes'].items():
            assert sha(path) == expected, path
        runner = Path(registration['runner'])
        spec = importlib.util.spec_from_file_location('e131_scope', runner)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        write('started.json', {'controller_pid': os.getpid(),
            'started_at': datetime.now(timezone.utc).isoformat(),
            'registration_sha256': sha(ROOT / 'registration.json')})
        module.start(Path(registration['repository']), Path(registration['plan']),
            Path(registration['study']), Path(registration['review']))
        execution = Path(registration['plan']).parent / 'execution'
        result = read(execution / 'execution-completion.json')
        assert result['status'] == 'complete'
        outcome = {'status': 'complete', 'exit_code': 0,
            'execution_completion_sha256': sha(execution / 'execution-completion.json'),
            'data_expansion_gate_passed': result['data_expansion_gate_passed']}
    except BaseException:
        outcome = {'status': 'stopped_with_error', 'exit_code': 1,
            'error': traceback.format_exc()}
        traceback.print_exc()
    outcome['finished_at'] = datetime.now(timezone.utc).isoformat()
    write('exit.json', outcome)
    return outcome['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
