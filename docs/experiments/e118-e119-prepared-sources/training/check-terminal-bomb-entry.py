"""Saved native evidence exercises relocated helpers and candidate admission."""
from pathlib import Path
import copy
import json

import scale_development as G
import candidate_original as O

T = Path(__file__).resolve().parent
A = T.parents[2] / 'ironclad-alignment'
S = A / 'evidence/e116-bomb-instance-repair-20260920-01'
read, write, sha = G.read, G.write, G.sha
G.registered()
registration = read(T / 'development-registration.json')
negative = []
for name in ('cohort.py', 'scale_development.py', 'candidate_original.py',
             'scale_training.py', 'terminal_rng.py', 'bomb_extras.py', 'bomb_instances.py'):
    path = next(p for p in registration['original_harness_sha256'] if Path(p).name == name)
    bad = copy.deepcopy(registration)
    # Change only the nested map; the outer hashes still validate. This exercises
    # the nested check itself rather than failing an unrelated earlier guard.
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
assert repair['status'] == 'complete'
for name in ('terminal-rng-verification.json', 'original-bomb-comparison.json',
             'recorded-bomb-comparison.json', 'bomb_extras.py', 'bomb_instances.py',
             'candidate-original/traces/1138994370.json',
             'candidate-original/original/1138994370-01/rpc.jsonl.gz'):
    assert sha(S / name) == repair['hashes'][name], name
O.ROOT, O.SOURCE = S / 'candidate-original', S / 'candidate'
O.modules()
import terminal_rng
import bomb_extras as B
import compare_cards as C
import compare_powers as P
assert Path(terminal_rng.__file__).resolve() == T / 'terminal_rng.py'
assert Path(B.__file__).resolve() == T / 'bomb_extras.py'
# The native harness prepends alignment/tests. Its stateless Bomb helper is a
# byte-identical copy; execution identity is the code hash, not its directory.
assert sha(B.bomb_instances.__file__) == sha(T / 'bomb_instances.py')
assert sha(B.__file__) == sha(S / 'bomb_extras.py')
assert sha(B.bomb_instances.__file__) == sha(S / 'bomb_instances.py')
terminal = terminal_rng.audit(O.ROOT, O.SOURCE, 1138994370)
assert terminal['status'] == 'matched' and terminal['natural_actions'] == 965
original = read(S / 'terminal-rng-verification.json')
assert {k: v for k, v in terminal.items() if k != 'script_sha256'} == {
    k: v for k, v in original.items() if k != 'script_sha256'}
identity = read(O.SOURCE / 'identity.json')
instance = {'status': 'matched', 'seed': terminal['seed'],
    'engine_sha256': identity['engine_sha256'],
    'combiner_sha256': sha(T / 'bomb_extras.py'),
    'instance_checker_sha256': sha(T / 'bomb_instances.py'),
    'trace_sha256': terminal['trace_sha256'], 'rpc_sha256': terminal['rpc_sha256'],
    'state_imports': 0, 'resynchronized': False}
for phase, name in (('live', 'original'), ('recorded', 'recorded')):
    prior = read(S / f'{name}-bomb-comparison.json')
    for key in ('status', 'engine_sha256', 'combiner_sha256', 'instance_checker_sha256',
                'state_imports', 'resynchronized'):
        assert prior[key] == instance[key], key
    instance[phase + '_checks'] = prior['checks']
    instance[phase + '_bomb_bearing_checks'] = prior['bomb_bearing_checks']
proof = {'status': 'complete', 'identity': identity, 'matched_routes': 1, 'attempted': 1,
    'requested_winning_routes': 1, 'unattempted_seeds': [], 'terminal_rng_streams_per_route': 12,
    'bomb_instance_comparison_required': True,
    'rows': [{'seed': terminal['seed'], 'status': 'matched', 'terminal_rng': terminal,
              'bomb_instances': instance}],
    'hashes': {f"traces/{terminal['seed']}.json": terminal['trace_sha256'],
        f"original/{terminal['seed']}-01/rpc.jsonl.gz": terminal['rpc_sha256']}}
G.require_original_complete(proof, [terminal['seed']], identity, sha(T / 'terminal_rng.py'),
                            sha(T / 'bomb_extras.py'), sha(T / 'bomb_instances.py'))
# This known natural route has no Bomb. Also exercise the relocated helpers on
# fifteen saved states with native Bomb instances and two corrupted controls.
source = A / 'evidence/e115-bomb-instance-diagnostic-20260920-01/original-controls/attempt-01/results.json'
assert sha(source) == 'b63381cdcd519ce0e2b7bdeb6fd3758e199f004d05e0bdd256302685b385a8e0'
rows = read(source)
positive = 0
for row in rows:
    for step in row['trace']:
        game = step['after']['game']
        if not B.bomb_instances.expected(game):
            continue
        battle = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
        assert not B.extras(game, battle)
        positive += 1
assert positive == 15
game = copy.deepcopy(rows[-1]['trace'][-2]['after']['game'])
game['combat_state']['player']['powers'] = [{'id': f'TheBomb{i}', 'amount': 1, 'damage': 40} for i in range(5)]
battle = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
corrupt = copy.deepcopy(game)
corrupt['combat_state']['player']['powers'] = [{'id': f'TheBomb{i}', 'amount': 1, 'damage': 50} for i in range(4)]
assert not P.extras(corrupt, battle), 'fixture must preserve the aggregate comparison'
assert set(B.extras(corrupt, battle)) == {'bomb_instances'}
corrupt = copy.deepcopy(game)
corrupt['combat_state']['player']['powers'][0]['amount'] = 2
assert 'bomb_instances' in B.extras(corrupt, battle)
assert sha(C.sts.__file__) == identity['engine_sha256']
assert not G.OUTPUT.exists() and not (T / 'original-candidates').exists()
write(T / 'terminal-bomb-entry-verification.json', {'status': 'passed',
    'checker_sha256': sha(__file__), 'registration_sha256': sha(T / 'development-registration.json'),
    'repair_completion_sha256': sha(S / 'completion-verification.json'),
    'terminal': terminal, 'bomb_instances_from_saved_full_route': instance,
    'nested_harness_negatives': negative,
    'candidate_admission_accepts_saved_native_evidence': True,
    'resolved_bomb_helper': {'path': B.bomb_instances.__file__,
        'sha256': sha(B.bomb_instances.__file__),
        'matches_frozen_candidate_copy': True},
    'native_bomb_control_states': positive, 'native_control_source_sha256': sha(source),
    'same_total_wrong_instances_rejected': True, 'wrong_countdown_rejected': True,
    'new_mcts_calls': 0, 'optimizer_updates': 0, 'new_original_executions': 0,
    'limits': 'Saved evidence and controlled snapshots only. The full route has no Bomb-bearing state; fifteen native control states test positive Bomb comparison. No learned candidate or population acceptance.'})
print({'status': 'passed', 'nested_harness_negatives': len(negative),
       'terminal_rng_streams': len(terminal['rng_streams']), 'natural_actions': terminal['natural_actions'],
       'native_bomb_control_states': positive, 'bomb_negative_controls': 2})
