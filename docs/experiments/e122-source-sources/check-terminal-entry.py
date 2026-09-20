"""Check the unchanged twelve-stream helper on completed E121 evidence and corruption controls."""
from pathlib import Path
import copy
import gzip
import hashlib
import json
import os
import sys

N = Path(__file__).resolve().parent
A = N.parents[2] / 'ironclad-alignment'
Q = A / 'evidence/e122-development-parity-20260920-01'
E = A / 'evidence/e121-power-order-repair-20260920-01'
os.environ['ALIGNMENT_BUILD'] = str(N / 'natural/engine')
os.environ['STS_LIGHTSPEED_BUILD'] = str(N / 'natural/engine')
sys.path.insert(0, str(Q))
import terminal_rng as T

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(T.__file__) == sha(A / 'evidence/e112-development-parity-20260920-01/terminal_rng.py')
proof = T.audit(E / 'candidate-original', E / 'candidate', 1138994370)
assert proof['status'] == 'matched' and proof['differences'] == {} and proof['natural_actions'] == json.loads((E / 'terminal-rng-verification.json').read_text())['natural_actions']
rpc = E / 'candidate-original/original/1138994370-01/rpc.jsonl.gz'
view = json.loads(gzip.decompress(rpc.read_bytes()).decode().splitlines()[-1])['response']['result']
native = view['rng']
actual = {name: T.C.bridge.rng_snapshot(native[name]) for name in proof['rng_streams']}
assert not T.compare_rng(native, actual)
negative = []
for name in proof['rng_streams']:
    bad = copy.deepcopy(actual); bad[name]['seed0'] ^= 1
    assert set(T.compare_rng(native, bad)) == {name}
    negative.append(name + '_seed0')
for name in ('missing_native', 'missing_simulator', 'invented_map_rng'):
    left, right = copy.deepcopy(native), copy.deepcopy(actual)
    if name == 'missing_native': del left['aiRng']
    elif name == 'missing_simulator': del right['aiRng']
    else: right['mapRng'] = T.C.bridge.rng_snapshot(native['mapRng'])
    try: T.compare_rng(left, right)
    except AssertionError: negative.append(name)
    else: raise AssertionError('invalid stream set accepted')
with (N / 'terminal-rng-entry-verification.json').open('x') as f:
    json.dump({'status': 'passed', 'helper_sha256': sha(T.__file__), 'checker_sha256': sha(__file__),
               'known_natural_replay': proof, 'negative_cases': negative,
               'new_original_instances': 0, 'MCTS_calls': 0, 'optimizer_updates': 0}, f, indent=2); f.write('\n')
print({'status': 'passed', 'known_actions_replayed': proof['natural_actions'], 'negative_cases': len(negative)})
