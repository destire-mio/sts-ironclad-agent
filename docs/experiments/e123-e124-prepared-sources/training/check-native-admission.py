"""Exercise relocated E124 comparators on saved native E121/E120/E115 evidence."""
from pathlib import Path
import copy
import scale_development as G
import candidate_original as O

T = G.ROOT
A = T.parents[2] / 'ironclad-alignment'
S = A / 'evidence/e121-power-order-repair-20260920-01'
read, write, sha = G.read, G.write, G.sha
G.registered()
registration = read(T / 'development-registration.json')
negative = []
for name in ('cohort.py', 'scale_development.py', 'candidate_original.py',
             'scale_training.py', 'terminal_rng.py', 'turn_extras.py', 'bomb_instances.py', 'power_order.py'):
    path = next(p for p in registration['original_harness_sha256'] if Path(p).name == name)
    bad = copy.deepcopy(registration)
    bad['original_harness_sha256'][path] = '0' * 64
    G.read = lambda p, value=bad: value if Path(p) == T / 'development-registration.json' else read(p)
    try:
        G.registered()
    except AssertionError as error:
        assert str(error) == path
        negative.append({'script': name, 'rejected': True})
    else:
        raise AssertionError('corrupted nested original harness was accepted')
    finally:
        G.read = read
G.registered()
repair = read(S / 'completion-verification.json')
assert repair['status'] == 'complete' and repair['source_refresh_permitted']
for name in ('terminal-rng-verification.json', 'original-turn-comparison.json', 'recorded-turn-comparison.json'):
    assert sha(S / name) == repair['hashes'][name], name
O.ROOT, O.SOURCE = S / 'candidate-original', S / 'candidate'
O.modules()
import terminal_rng
import turn_extras as B
import compare_cards as C
import compare_powers as P
assert Path(terminal_rng.__file__).resolve() == T / 'terminal_rng.py'
assert Path(B.__file__).resolve() == T / 'turn_extras.py'
for module, name in ((B, 'turn_extras.py'), (B.bomb_instances, 'bomb_instances.py'), (B.power_order, 'power_order.py')):
    assert sha(module.__file__) == sha(T / name) == sha(S / name)
terminal = terminal_rng.audit(O.ROOT, O.SOURCE, 1138994370)
assert terminal['status'] == 'matched'
original = read(S / 'terminal-rng-verification.json')
assert {k: v for k, v in terminal.items() if k != 'script_sha256'} == {
    k: v for k, v in original.items() if k != 'script_sha256'}
identity = read(O.SOURCE / 'identity.json')
common = {'status': 'matched', 'seed': terminal['seed'], 'engine_sha256': identity['engine_sha256'],
    'combiner_sha256': sha(T / 'turn_extras.py'), 'trace_sha256': terminal['trace_sha256'],
    'rpc_sha256': terminal['rpc_sha256'], 'state_imports': 0, 'resynchronized': False}
instance = dict(common, instance_checker_sha256=sha(T / 'bomb_instances.py'))
order = dict(common, order_checker_sha256=sha(T / 'power_order.py'), phases=['end', 'start', 'post_draw'])
for phase, name in (('live', 'original'), ('recorded', 'recorded')):
    prior = read(S / f'{name}-turn-comparison.json')
    for key in ('status', 'engine_sha256', 'combiner_sha256', 'instance_checker_sha256', 'state_imports', 'resynchronized'):
        assert prior[key] == instance[key], key
    assert prior['order_checker_sha256'] == order['order_checker_sha256']
    instance[phase + '_checks'] = order[phase + '_checks'] = prior['checks']
    instance[phase + '_bomb_bearing_checks'] = prior['bomb_bearing_checks']
    order[phase + '_order_bearing_checks'] = prior['order_bearing_checks']
proof = {'status': 'complete', 'identity': identity, 'matched_routes': 1, 'attempted': 1,
    'requested_winning_routes': 1, 'unattempted_seeds': [], 'terminal_rng_streams_per_route': 12,
    'bomb_instance_comparison_required': True, 'turn_order_comparison_required': True,
    'rows': [{'seed': terminal['seed'], 'status': 'matched', 'terminal_rng': terminal,
              'bomb_instances': instance, 'turn_order': order}],
    'hashes': {f"traces/{terminal['seed']}.json": terminal['trace_sha256'],
        f"original/{terminal['seed']}-01/rpc.jsonl.gz": terminal['rpc_sha256']}}
G.require_original_complete(proof, [terminal['seed']], identity, sha(T / 'terminal_rng.py'),
    sha(T / 'turn_extras.py'), sha(T / 'bomb_instances.py'), sha(T / 'power_order.py'))

bomb_source = A / 'evidence/e115-bomb-instance-diagnostic-20260920-01/original-controls/attempt-01/results.json'
assert sha(bomb_source) == 'b63381cdcd519ce0e2b7bdeb6fd3758e199f004d05e0bdd256302685b385a8e0'
bomb_rows = read(bomb_source)
bomb_positive = 0
for row in bomb_rows:
    for step in row['trace']:
        game = step['after']['game']
        if not B.bomb_instances.expected(game):
            continue
        battle = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
        assert not B.extras(game, battle)
        bomb_positive += 1
assert bomb_positive == 15
game = copy.deepcopy(bomb_rows[-1]['trace'][-2]['after']['game'])
game['combat_state']['player']['powers'] = [{'id': f'TheBomb{i}', 'amount': 1, 'damage': 40} for i in range(5)]
battle = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
corrupt = copy.deepcopy(game)
corrupt['combat_state']['player']['powers'] = [{'id': f'TheBomb{i}', 'amount': 1, 'damage': 50} for i in range(4)]
assert not P.extras(corrupt, battle)
assert 'bomb_instances' in B.extras(corrupt, battle)
corrupt = copy.deepcopy(game)
corrupt['combat_state']['player']['powers'][0]['amount'] = 2
assert 'bomb_instances' in B.extras(corrupt, battle)

order_source = A / 'evidence/e120-end-turn-order-diagnostic-20260920-01/original-controls/attempt-01/results.json'
source_entry = read(T.parent / 'heart-e121-scale-source-refresh-20260920-01/turn-entry-verification.json')
assert sha(order_source) == source_entry['source_sha256']
order_rows = read(order_source)
order_positive = 0
for row in order_rows:
    for step in row['trace']:
        game = step['after']['game']
        battle = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
        assert not B.extras(game, battle)
        order_positive += 1
assert order_positive == 11
game = copy.deepcopy(order_rows[0]['trace'][1]['after']['game'])
battle = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
game['combat_state']['player']['powers'].reverse()
assert not P.extras(game, battle)
assert 'player_power_order_end' in B.extras(game, battle)
assert sha(C.sts.__file__) == identity['engine_sha256']
assert not G.OUTPUT.exists() and not (T / 'original-candidates').exists()
write(T / 'native-admission-verification.json', {'status': 'passed',
    'checker_sha256': sha(__file__), 'registration_sha256': sha(T / 'development-registration.json'),
    'repair_completion_sha256': sha(S / 'completion-verification.json'),
    'saved_native_admission': proof, 'nested_harness_negatives': negative,
    'resolved_bomb_helper': {'path': B.bomb_instances.__file__, 'sha256': sha(B.bomb_instances.__file__)},
    'native_bomb_control_states': bomb_positive, 'native_order_control_states': order_positive,
    'control_sources_sha256': {str(p): sha(p) for p in (bomb_source, order_source)},
    'same_total_wrong_bomb_instances_rejected': True, 'wrong_countdown_rejected': True,
    'same_amount_wrong_turn_order_rejected': True,
    'new_mcts_calls': 0, 'optimizer_updates': 0, 'new_original_executions': 0,
    'limits': 'Saved native evidence and controlled snapshots; no learned candidate or population acceptance. The natural route has no Bomb-bearing state; positive Bomb coverage comes from the fifteen control states.'})
print({'status': 'passed', 'nested_harness_negatives': len(negative),
    'native_bomb_states': bomb_positive, 'native_order_states': order_positive,
    'terminal_rng_streams': len(terminal['rng_streams']), 'natural_actions': terminal['natural_actions']})
