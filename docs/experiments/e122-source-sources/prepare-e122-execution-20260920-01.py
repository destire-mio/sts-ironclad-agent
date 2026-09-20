"""Reuse the owned wrapper; add turn-order admission and corruption checks."""
from pathlib import Path
from datetime import datetime, timezone
import ast
import hashlib
import json
import shutil
import subprocess
import sys

R = Path(__file__).resolve().parents[1]
A = R.parent / 'ironclad-alignment'
OLD = R / 'runs/heart-e116-scale-source-refresh-20260920-01'
N = R / 'runs/heart-e121-scale-source-refresh-20260920-01'
Q = A / 'evidence/e122-development-parity-20260920-01'
E = A / 'evidence/e121-power-order-repair-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')
def rebound(text):
    for before, after in [(OLD.name, N.name), ('e117-development-parity', 'e122-development-parity'),
            ('e116-bomb-instance-repair', 'e121-power-order-repair'), ('E117', 'E122'), ('E116', 'E121')]:
        text = text.replace(before, after)
    return text
def script(name, changes=()):
    text = rebound((OLD / name).read_text())
    for before, after in changes:
        assert text.count(before) == 1, (name, before)
        text = text.replace(before, after)
    ast.parse(text)
    with (N / name).open('x') as f: f.write(text)
def run(name, *args):
    with (N / (name + '.log')).open('x') as f:
        subprocess.run([sys.executable, N / name, *args], stdout=f, stderr=subprocess.STDOUT, check=True)

assert read(E / 'completion-verification.json')['status'] == 'complete'
assert read(N / 'preparation-bindings.json')['status'] == 'prepared_not_launched'
script('check-bomb-entry.py', [
    ('import bomb_extras as B', 'import turn_extras as B'),
    ("assert set(B.extras(corrupt, b)) == {'bomb_instances'}", "assert 'bomb_instances' in B.extras(corrupt, b)")])
script('check-terminal-entry.py', [
    ("proof['natural_actions'] == 965", "proof['natural_actions'] == json.loads((E / 'terminal-rng-verification.json').read_text())['natural_actions']")])
for name in ('check-bomb-entry.py', 'check-terminal-entry.py'): run(name)

entry = '''"""Check observed native turn orders and fail closed on corrupt admission proofs."""
from pathlib import Path
import copy, hashlib, importlib.util, json, os, sys
N = Path(__file__).resolve().parent
A = N.parents[2] / 'ironclad-alignment'
Q = A / 'evidence/e122-development-parity-20260920-01'
E = A / 'evidence/e121-power-order-repair-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
os.environ.update(ALIGNMENT_BUILD=str(N / 'natural/engine'), STS_LIGHTSPEED_BUILD=str(N / 'natural/engine'))
sys.path[:0] = [str(Q), str(A / 'tests')]
import turn_extras as B
import compare_cards as C
import compare_powers as P
spec = importlib.util.spec_from_file_location('e122_gate', Q / 'cohort.py')
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
source = A / 'evidence/e120-end-turn-order-diagnostic-20260920-01/original-controls/attempt-01/results.json'
rows = read(source); positive = 0
for row in rows:
    for step in row['trace']:
        game = step['after']['game']
        b = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
        assert not B.extras(game, b)
        positive += 1
game = copy.deepcopy(rows[0]['trace'][1]['after']['game'])
b = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
game['combat_state']['player']['powers'].reverse()
assert not P.extras(game, b)
assert 'player_power_order_end' in B.extras(game, b)
identity = read(N / 'natural/identity.json')
live, recorded = [read(E / (mode + '-turn-comparison.json')) for mode in ('original', 'recorded')]
seed = 1138994370
trace_sha = sha(E / f'candidate-original/traces/{seed}.json')
rpc_sha = sha(E / f'candidate-original/original/{seed}-01/rpc.jsonl.gz')
proof = dict(status='matched', seed=seed, engine_sha256=identity['engine_sha256'],
    combiner_sha256=sha(Q / 'turn_extras.py'), order_checker_sha256=sha(Q / 'power_order.py'),
    phases=['end', 'start', 'post_draw'], live_checks=live['checks'], recorded_checks=recorded['checks'],
    live_order_bearing_checks=live['order_bearing_checks'], recorded_order_bearing_checks=recorded['order_bearing_checks'],
    trace_sha256=trace_sha, rpc_sha256=rpc_sha, state_imports=0, resynchronized=False)
G.require_turn_order(proof, seed, identity, trace_sha, rpc_sha)
negative = []
for field, value in [('status', 'failed'), ('seed', seed + 1), ('engine_sha256', 'wrong'),
        ('combiner_sha256', 'wrong'), ('order_checker_sha256', 'wrong'), ('phases', ['end']),
        ('live_checks', 0), ('recorded_checks', 0), ('live_checks', True), ('recorded_checks', 1.5),
        ('live_order_bearing_checks', -1), ('recorded_order_bearing_checks', proof['recorded_checks'] + 1),
        ('live_order_bearing_checks', True), ('recorded_order_bearing_checks', 1.5),
        ('state_imports', 1), ('resynchronized', True), ('trace_sha256', 'wrong'), ('rpc_sha256', 'wrong')]:
    corrupt = copy.deepcopy(proof); corrupt[field] = value
    try: G.require_turn_order(corrupt, seed, identity, trace_sha, rpc_sha)
    except (AssertionError, KeyError): negative.append(field + ':' + repr(value))
    else: raise AssertionError('corrupt order proof admitted: ' + field)
for field in ('phases', 'live_checks', 'recorded_checks', 'order_checker_sha256'):
    corrupt = copy.deepcopy(proof); del corrupt[field]
    try: G.require_turn_order(corrupt, seed, identity, trace_sha, rpc_sha)
    except (AssertionError, KeyError): negative.append('missing:' + field)
    else: raise AssertionError('incomplete order proof admitted: ' + field)
assert not (N / 'natural/episodes').exists() and not (Q / 'original').exists()
result = dict(status='passed', original_control_states=positive, wrong_order_same_amount_rejected=True,
    legacy_comparator_accepts_wrong_order=True, known_integration_seed=seed, positive_proof=proof,
    negative_cases=negative, source_sha256=sha(source), checker_sha256=sha(__file__),
    engine_sha256=sha(C.sts.__file__), new_original_instances=0, MCTS_calls=0, optimizer_updates=0)
with (N / 'turn-entry-verification.json').open('x') as f: json.dump(result, f, indent=2); f.write('\\n')
print({'status': 'passed', 'native_states': positive, 'negative_proofs': len(negative)})
'''
ast.parse(entry)
with (N / 'check-turn-entry.py').open('x') as f: f.write(entry)
run('check-turn-entry.py')
script('run_job.py', [
    ("    assert read(N / 'bomb-entry-verification.json')['status'] == 'passed'", "    assert read(N / 'bomb-entry-verification.json')['status'] == 'passed'\n    assert read(N / 'turn-entry-verification.json')['status'] == 'passed'"),
    ("else: assert proof['bomb_instance_comparison_required'] and proof['terminal_rng_streams_per_route'] == 12",
     "else: assert proof['bomb_instance_comparison_required'] and proof['turn_order_comparison_required'] and proof['terminal_rng_streams_per_route'] == 12")])
script('observe.py', [
    ('schedule = read(schedule_path)', "schedule = read(schedule_path)\nif schedule['status'] != 'running':\n    print({'stopped': True, 'status': schedule['status']}); raise SystemExit(0)")])
prior = read(OLD / 'execution-registration.json')
hashes = {}
for path, expected in prior['hashes'].items():
    if str(OLD) in path or 'e117-development-parity' in path:
        rebound_path = rebound(path)
        if Path(rebound_path).name == 'bomb_extras.py': rebound_path = str(Q / 'turn_extras.py')
        if Path(rebound_path).name == 'preparation-source.py': continue
        hashes[rebound_path] = sha(rebound_path)
    else:
        assert sha(path) == expected, path
        hashes[path] = expected
for path in [N / 'check-turn-entry.py', N / 'turn-entry-verification.json',
             Q / 'power_order.py', Q / 'turn_extras.py', N / 'preparation-source.py']:
    hashes[str(path)] = sha(path)
shutil.copyfile(__file__, N / 'execution-preparation-source.py')
hashes[str(N / 'execution-preparation-source.py')] = sha(__file__)
write(N / 'execution-registration.json', dict(experiment='E122-execution',
    created_at=datetime.now(timezone.utc).isoformat(), owned_launcher=prior['owned_launcher'],
    wrapper_seconds=prior['wrapper_seconds'], long_job_observation_seconds=1200,
    source_invocations=1, original_gate_invocations=1, hashes=hashes))
run('run_job.py', 'source', '--check')
with (N / 'original-admission-check.log').open('x') as f:
    rejected = subprocess.run([sys.executable, N / 'run_job.py', 'original', '--check'],
        stdout=f, stderr=subprocess.STDOUT)
assert rejected.returncode != 0
assert 'development source incomplete' in (N / 'original-admission-check.log').read_text()
assert not (N / 'source-job').exists() and not (N / 'original-job').exists()
write(N / 'wrapper-entry-verification.json', dict(status='passed', source_admitted=True,
    incomplete_original_rejected_before_launch=True, wrapper_sha256=sha(N / 'run_job.py'),
    registration_sha256=sha(N / 'execution-registration.json'),
    owned_launcher_sha256=sha(prior['owned_launcher']),
    reused_process_controls=read(Path(prior['owned_launcher']).parent / 'launcher-probe/completion-verification.json')['status']))
print({'status': 'prepared_not_launched', 'turn_order_negative_proofs': 22, 'source_families': 6144})
