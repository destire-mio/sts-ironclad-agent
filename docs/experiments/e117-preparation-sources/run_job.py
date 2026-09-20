"""Run one E117 source/original job with the previously tested owned-process utility."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import sys

N = Path(__file__).resolve().parent
A = N.parents[2] / 'ironclad-alignment'
Q = A / 'evidence/e117-development-parity-20260920-01'
S = N / 'natural'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')

def admit(mode):
    assert mode in ('source', 'original')
    reg = read(N / 'execution-registration.json')
    for path, expected in reg['hashes'].items(): assert sha(path) == expected, path
    for path, expected in read(Q / 'registration.json')['harness_sha256'].items(): assert sha(path) == expected, path
    for name, expected in read(S / 'manifest.json')['frozen_files'].items(): assert sha(S / name) == expected, name
    assert read(N / 'runtime-entry-verification.json')['status'] == 'complete'
    assert read(N / 'original-entry-verification.json')['registration_sha256'] == sha(Q / 'registration.json')
    assert read(N / 'bomb-entry-verification.json')['status'] == 'passed'
    assert not (N / (mode + '-job')).exists(), 'preserve the first execution'
    if mode == 'source':
        assert not (S / 'episodes').exists()
    else:
        seeds = read(Q / 'registration.json')['development_seeds']
        assert all((S / f'episodes/{seed}.json.gz').is_file() for seed in seeds), 'development source incomplete'
        assert not (Q / 'execution-started.json').exists()
    return reg

def main():
    mode = sys.argv[1]
    reg = admit(mode)
    if '--check' in sys.argv:
        print({'status': 'admitted_without_launch', 'mode': mode}); return 0
    entry = read(N / 'wrapper-entry-verification.json')
    assert entry['status'] == 'passed' and entry['source_admitted'] and entry['incomplete_original_rejected_before_launch']
    assert entry['wrapper_sha256'] == sha(__file__) and entry['registration_sha256'] == sha(N / 'execution-registration.json')
    sys.path.insert(0, str(Path(reg['owned_launcher']).parent))
    import run_pipeline as owned
    assert sha(owned.__file__) == reg['hashes'][str(Path(owned.__file__))]
    root = N / (mode + '-job'); root.mkdir()
    env = dict(os.environ, HEART_BRANCH_RUNTIME=str(S), ALIGNMENT_BUILD=str(S / 'engine'),
               STS_LIGHTSPEED_BUILD=str(S / 'engine'), OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    command = [sys.executable, str(S / 'run_refresh.py'), 'run', '--root', str(S)] if mode == 'source' else [sys.executable, str(Q / 'cohort.py')]
    try:
        result = owned.run_owned(root, command, env, reg['wrapper_seconds'], sha(N / 'execution-registration.json'))
    finally:
        if mode == 'original':
            sys.path.insert(0, str(A / 'oracle'))
            import run as O
            cleanup = []
            for instance in (Q / 'original').glob('*/instance'):
                O.stop(instance)
                if O.instance_processes(instance): O.stop(instance, force=True)
                cleanup.append({'instance': str(instance), 'remaining': O.instance_processes(instance)})
            write(root / 'native-cleanup.json', {'instances': cleanup})
            assert all(not row['remaining'] for row in cleanup)
    output = {'exit_code': result['exit_code'], 'finished_at': datetime.now(timezone.utc).isoformat(),
              'process_exit_sha256': sha(root / 'pipeline-process-exit.json')}
    if result['exit_code'] == 0:
        folder = S if mode == 'source' else Q
        proof = read(folder / 'completion-verification.json')
        assert proof['status'] == 'complete'
        for name, expected in proof['hashes'].items(): assert sha(folder / name) == expected
        if mode == 'source': assert proof['natural_terminals'] == 6144 and proof['zero_faults']
        else: assert proof['bomb_instance_comparison_required'] and proof['terminal_rng_streams_per_route'] == 12
        output['completion_sha256'] = sha(folder / 'completion-verification.json')
    write(N / (mode + '-execution.json'), output)
    print(output, flush=True)
    return result['exit_code']

if __name__ == '__main__': raise SystemExit(main())
