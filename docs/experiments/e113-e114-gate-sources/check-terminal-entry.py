"""Exercise the relocated terminal helper and nested harness rejection on saved evidence."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json

import scale_development as G
import candidate_original as O

T = Path(__file__).resolve().parent
S = T.parents[2] / 'ironclad-alignment/evidence/e111-post-victory-exhaust-repair-20260920-01'
read, write, sha = G.read, G.write, G.sha
G.registered()
registration = read(T / 'development-registration.json')
stale = read(T / 'source-renewal-verification.json')['stale_inherited_nested_harness_hashes_rejected']
negative = []
for old_path, item in stale.items():
    name = Path(old_path).name
    current_path = next(p for p in registration['original_harness_sha256'] if Path(p).name == name)
    bad = copy.deepcopy(registration)
    bad['original_harness_sha256'][current_path] = item['recorded_sha256']
    assert bad['original_harness_sha256'][current_path] != sha(current_path)
    G.read = lambda p, value=bad: value if Path(p) == T / 'development-registration.json' else read(p)
    try:
        G.registered()
    except AssertionError as error:
        assert str(error) == current_path
        negative.append({'script': name, 'rejected': True})
    else:
        raise AssertionError('stale nested original harness was accepted')
    finally:
        G.read = read
G.registered()
O.ROOT, O.SOURCE = S / 'candidate-original', S / 'candidate'
O.modules()
import terminal_rng
assert Path(terminal_rng.__file__).resolve() == T / 'terminal_rng.py'
terminal = terminal_rng.audit(O.ROOT, O.SOURCE, 1138994370)
assert terminal['status'] == 'matched' and terminal['natural_actions'] == 965
original = json.loads((S / 'terminal-rng-verification.json').read_text())
assert {k: v for k, v in terminal.items() if k != 'script_sha256'} == {
    k: v for k, v in original.items() if k != 'script_sha256'}
identity = read(O.SOURCE / 'identity.json')
proof = {'status': 'complete', 'identity': identity, 'matched_routes': 1, 'attempted': 1,
    'requested_winning_routes': 1, 'unattempted_seeds': [], 'terminal_rng_streams_per_route': 12,
    'rows': [{'seed': terminal['seed'], 'status': 'matched', 'terminal_rng': terminal}],
    'hashes': {f"traces/{terminal['seed']}.json": terminal['trace_sha256'],
        f"original/{terminal['seed']}-01/rpc.jsonl.gz": terminal['rpc_sha256']}}
G.require_original_complete(proof, [terminal['seed']], identity, sha(T / 'terminal_rng.py'))
write(T / 'terminal-entry-verification.json', {'status': 'passed',
    'checker_sha256': sha(__file__), 'registration_sha256': sha(T / 'development-registration.json'),
    'terminal': terminal, 'nested_harness_negatives': negative,
    'candidate_admission_accepts_actual_terminal_proof': True,
    'new_mcts_calls': 0, 'optimizer_updates': 0, 'new_original_executions': 0,
    'limits': 'Replay of one previously verified original route, not a new candidate evaluation.'})
print({'status': 'passed', 'nested_harness_negatives': len(negative),
       'terminal_rng_streams': len(terminal['rng_streams']), 'natural_actions': terminal['natural_actions']})
