"""Check real native Bomb observations and reject same-total instance corruption."""
from pathlib import Path
import copy
import hashlib
import json
import os
import sys

N = Path(__file__).resolve().parent
A = N.parents[2] / 'ironclad-alignment'
Q = A / 'evidence/e122-development-parity-20260920-01'
S = N / 'natural'
os.environ['ALIGNMENT_BUILD'] = str(S / 'engine')
os.environ['STS_LIGHTSPEED_BUILD'] = str(S / 'engine')
sys.path[:0] = [str(Q), str(A / 'tests')]
import turn_extras as B
import compare_cards as C
import compare_powers as P

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
source = A / 'evidence/e115-bomb-instance-diagnostic-20260920-01/original-controls/attempt-01/results.json'
rows = json.loads(source.read_text())
positive = 0
for row in rows:
    for step in row['trace']:
        game = step['after']['game']
        if not B.bomb_instances.expected(game): continue
        b = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
        assert not B.extras(game, b)
        positive += 1
game = copy.deepcopy(rows[-1]['trace'][-2]['after']['game'])
game['combat_state']['player']['powers'] = [{'id': f'TheBomb{i}', 'amount': 1, 'damage': 40} for i in range(5)]
b = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
corrupt = copy.deepcopy(game)
corrupt['combat_state']['player']['powers'] = [{'id': f'TheBomb{i}', 'amount': 1, 'damage': 50} for i in range(4)]
assert not P.extras(corrupt, b), 'negative fixture must preserve the old aggregate comparison'
assert 'bomb_instances' in B.extras(corrupt, b)
wrong_timer = copy.deepcopy(game); wrong_timer['combat_state']['player']['powers'][0]['amount'] = 2
assert 'bomb_instances' in B.extras(wrong_timer, b)
assert not (S / 'episodes').exists() and not (Q / 'original').exists()
proof = {'status': 'passed', 'original_control_states': positive,
         'same_total_wrong_instances_rejected': True, 'wrong_countdown_rejected': True,
         'legacy_comparator_accepts_same_total_negative_control': True,
         'source_sha256': sha(source), 'engine_sha256': sha(C.sts.__file__),
         'combiner_sha256': sha(B.__file__), 'instance_checker_sha256': sha(B.bomb_instances.__file__),
         'checker_sha256': sha(__file__), 'new_original_instances': 0, 'MCTS_calls': 0,
         'scope': 'Controlled power-state import and comparison; not natural source generation or native route acceptance.'}
with (N / 'bomb-entry-verification.json').open('x') as f: json.dump(proof, f, indent=2); f.write('\n')
print(proof)
