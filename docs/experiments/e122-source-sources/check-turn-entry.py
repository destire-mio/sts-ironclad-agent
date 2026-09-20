"""Check observed native turn orders and fail closed on corrupt admission proofs."""
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
with (N / 'turn-entry-verification.json').open('x') as f: json.dump(result, f, indent=2); f.write('\n')
print({'status': 'passed', 'native_states': positive, 'negative_proofs': len(negative)})
