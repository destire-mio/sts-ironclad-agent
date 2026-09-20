"""Bounded E121 integration; stages advance on completion, observations every 20 minutes."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import gzip
import hashlib
import json
import os
import subprocess
import sys

Q = Path(__file__).resolve().parent
A = Q.parents[1]
R = A.parent / 'sts-rl-agent-pr'
C, N = Q / 'candidate', Q / 'candidate-original'
SEED = 1138994370
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
    return json.loads(gzip.decompress(p.read_bytes())) if p.suffix == '.gz' else json.loads(p.read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')
def command(name, argv, seconds):
    with (Q / (name + '.log')).open('x') as log:
        subprocess.run([sys.executable, *map(str, argv)], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=seconds, cwd=Q)
def verify_registration():
    reg = read(Q / 'integration-registration.json')
    for path, expected in reg['hashes'].items(): assert sha(path) == expected, path
    return reg

def original_plan():
    proof = read(C / 'completion-verification.json')
    assert proof['status'] == 'complete' and proof['zero_faults'] and proof['natural_terminals'] == 1
    for name, expected in proof['hashes'].items(): assert sha(C / name) == expected
    row = read(C / f'episodes/{SEED}.json.gz')
    assert row['seed'] == SEED and row['status'] in ('heart_win', 'death')
    assert row['replay_verified'] and row['terminal_state_verified']
    N.mkdir()
    write(N / 'plan.json', {
        'experiment': 'E121-original-integration', 'registered_at': datetime.now(timezone.utc).isoformat(),
        'source_cohort': str(C), 'source_runtime': str(C), 'source_report': str(C / 'report.json'),
        'source_report_sha256': sha(C / 'report.json'),
        'source_episode_sha256': {str(SEED): sha(C / f'episodes/{SEED}.json.gz')},
        'candidate_model_sha256': sha(C / 'model.pt'),
        'engine_sha256': sha(C / 'engine/slaythespire.cpython-312-darwin.so'),
        'reference_game_sha256': 'dd60a613a6178e08f1a57bcb8d5747e33c21fd49e743b88d76e9d74042803b2a',
        'seeds': [SEED], 'expected_terminal_status': row['status'],
        'resynchronization_permitted': False, 'original_timeout_seconds': 900,
        'long_job_observation_interval_seconds': 1200,
        'selection': 'Preselected E121 known route; no replacement or change to outcome.',
        'scope': 'Full natural original replay plus independent Bomb-instance and turn-order comparison; not unseen evaluation.',
        'harness_before_execution': read(Q / 'integration-registration.json')['hashes']})

def native_or_recorded(mode):
    sys.path.insert(0, str(A / 'tests'))
    import verify_heart_winners as V
    modules = V.setup(N)
    import turn_extras as B
    modules[-1].extras = B.extras
    if mode == 'original':
        result = V.one(N, SEED, 1, modules)
        required = 'original_' + ('heart' if read(N / 'plan.json')['expected_terminal_status'] == 'heart_win' else 'death') + '_trace_matched'
    else:
        import replay_recorded_winner as K
        result = K.run(N / 'recorded')
        required = 'recorded_original_' + ('heart' if read(N / 'plan.json')['expected_terminal_status'] == 'heart_win' else 'death') + '_trace_matched'
    write(Q / (mode + '-turn-comparison.json'), {
        'status': 'matched' if result['status'] == required else 'failed', 'checks': B.checks,
        'bomb_bearing_checks': B.bomb_bearing_checks, 'engine_sha256': sha(modules[4].sts.__file__),
        'combiner_sha256': sha(B.__file__), 'instance_checker_sha256': sha(Q / 'bomb_instances.py'),
        'order_checker_sha256': sha(Q / 'power_order.py'),
        'order_bearing_checks': B.order_bearing_checks,
        'result_status': result['status'], 'state_imports': 0, 'resynchronized': False})
    assert result['status'] == required, result

def pipeline():
    verify_registration()
    command('candidate-run', [C / 'run_refresh.py', 'run', '--root', C], 900)
    original_plan()
    command('original-run', [__file__, 'original'], 900)
    command('prepare-recorded', [Q / 'prepare-recorded.py'], 30)
    command('recorded-replay', [__file__, 'recorded'], 120)
    command('terminal-rng', [Q / 'audit-terminal-rng.py'], 120)
    write(Q / 'integration-stages-complete.json', {
        'status': 'complete', 'finished_at': datetime.now(timezone.utc).isoformat(),
        'registration_sha256': sha(Q / 'integration-registration.json'),
        'natural_completion_sha256': sha(C / 'completion-verification.json'),
        'original_turn_comparison_sha256': sha(Q / 'original-turn-comparison.json'),
        'recorded_turn_comparison_sha256': sha(Q / 'recorded-turn-comparison.json'),
        'terminal_rng_sha256': sha(Q / 'terminal-rng-verification.json')})

def launch():
    reg = verify_registration()
    launcher_dir = Path(reg['owned_launcher']).parent
    sys.path.insert(0, str(launcher_dir))
    import run_pipeline as owned
    assert sha(owned.__file__) == reg['hashes'][str(Path(owned.__file__))]
    env = dict(os.environ, HEART_BRANCH_RUNTIME=str(C), ALIGNMENT_BUILD=str(C / 'engine'),
               STS_LIGHTSPEED_BUILD=str(C / 'engine'), OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    now = datetime.now(timezone.utc)
    write(Q / 'observation-schedule.json', {'status': 'running', 'interval_seconds': 1200,
        'started_at': now.isoformat(), 'next_observation_at': (now + timedelta(seconds=1200)).isoformat()})
    try:
        result = owned.run_owned(Q, [sys.executable, '-u', __file__, 'pipeline'], env, 2400,
                                 sha(Q / 'integration-registration.json'))
    finally:
        # The original adapter owns a separate JVM group; clean only this new
        # integration's isolated instance even after wrapper timeout/interruption.
        sys.path.insert(0, str(A / 'oracle'))
        import run as O
        cleanups = []
        for instance in (N / 'original').glob('*/instance'):
            O.stop(instance)
            if O.instance_processes(instance): O.stop(instance, force=True)
            cleanups.append({'instance': str(instance), 'remaining': O.instance_processes(instance)})
        write(Q / 'integration-native-cleanup.json', {'instances': cleanups})
    assert all(not row['remaining'] for row in cleanups)
    print({'exit_code': result['exit_code'], 'cleanup': result['cleanup']}, flush=True)
    return result['exit_code']

if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'launch': raise SystemExit(launch())
    if mode == 'pipeline': pipeline()
    elif mode in ('original', 'recorded'): verify_registration(); native_or_recorded(mode)
    else: raise ValueError(mode)
