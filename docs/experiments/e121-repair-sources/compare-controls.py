"""Replay original E120 sequences, then explicit snapshot/clone suffix checks."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import sys

Q = Path(__file__).resolve().parent
A = Q.parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
os.environ['ALIGNMENT_BUILD'] = str(args.build.resolve())
os.environ['ALIGNMENT_STRICT'] = '1'
assert os.environ.get('ALIGNMENT_REIMPORT') != '1'
sys.path[:0] = [str(Q), str(A / 'tests')]
import compare_sequences as C
import compare_powers as P
import power_order as O
import bomb_instances as B

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
legacy = P.extras
checks = 0
def extras(game, battle):
    global checks
    checks += 1
    return {**legacy(game, battle), **B.differences(game, battle),
            **O.differences(game, battle, C.bridge)}
P.extras = extras

source = Q.parent / 'e120-end-turn-order-diagnostic-20260920-01/original-controls/attempt-01/results.json'
rows = json.loads(source.read_text())
assert len(rows) == 4 and all(row['status'] == 'executed' for row in rows)
results = [C.compare_sequence(row) for row in rows]
assert all(r['status'] == 'passed' for r in results), results

def imported(view):
    game = copy.deepcopy(view['game'])
    game['combat_state']['rngs'] = {k: view['rng'][v] for k, v in C.RNG_NAMES.items()}
    return C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)

def difference(view, battle):
    wanted, got = C.original(view['game']), C.simulator(battle)
    wanted['rng'] = {k: C.bridge.rng_snapshot(view['rng'][v]) for k, v in C.RNG_NAMES.items()}
    got['rng'] = battle.rng_states
    return {**{k: {'original': wanted[k], 'simulator': got[k]} for k in wanted if wanted[k] != got[k]},
            **extras(view['game'], battle)}

def execute(battle, command):
    words = command.split()
    if words[0] == 'end': action = C.sts.SearchAction(C.sts.SearchActionType.END_TURN)
    else:
        assert words[0] == 'play'
        action = C.sts.SearchAction(C.sts.SearchActionType.CARD, int(words[1]) - 1, 0)
    assert action.is_valid(battle)
    action.execute(battle)

suffixes = []
for row in rows:
    for index, step in enumerate(row['trace'][:-1]):
        battle = imported(step['after'])
        assert not difference(step['after'], battle)
        sibling = battle.clone()
        before = C.simulator(sibling), O.actual(sibling), P.player_actual(sibling), sibling.rng_states
        for later in row['trace'][index + 1:]:
            execute(battle, later['command'])
            assert not difference(later['after'], battle), difference(later['after'], battle)
        assert (C.simulator(sibling), O.actual(sibling), P.player_actual(sibling), sibling.rng_states) == before
        for later in row['trace'][index + 1:]:
            execute(sibling, later['command'])
            assert not difference(later['after'], sibling)
        assert repr(battle) == repr(sibling) and battle.rng_states == sibling.rng_states
        suffixes.append({'case': row['spec']['name'], 'after_action': index})

# Same power names and amounts, but reversed order must fail the additive check.
view = rows[0]['trace'][1]['after']
battle = imported(view)
tampered = copy.deepcopy(view['game'])
tampered['combat_state']['player']['powers'].reverse()
assert O.differences(tampered, battle, C.bridge)
assert P.player_expected(tampered) == P.player_actual(battle)
reverse = imported({**view, 'game': tampered})
assert repr(battle) != repr(reverse)
execute(battle, 'end'); execute(reverse, 'end')
assert len(battle.draw_pile) == 4 and len(reverse.draw_pile) == 3

proof = {'status': 'matched', 'engine_sha256': sha(C.sts.__file__), 'source_sha256': sha(source),
    'checker_sha256': sha(__file__), 'order_checker_sha256': sha(O.__file__),
    'bomb_checker_sha256': sha(B.__file__), 'sequence_driver_sha256': sha(C.__file__),
    'legacy_power_checker_sha256': sha(P.__file__), 'results': results,
    'order_comparisons': checks, 'snapshot_suffixes': suffixes,
    'wrong_order_same_amount_rejected': True, 'wrong_order_changes_next_draw': True,
    'sequence_initial_imports': 4, 'mid_sequence_resynchronized': False,
    'limits': 'Four native controlled sequences and seven explicitly imported suffixes. Not a natural seed or model improvement. Berserk stays represented by energy; zero scalar powers use existing presence semantics.'}
with args.out.open('x') as f: json.dump(proof, f, indent=2); f.write('\n')
print({'status': 'matched', 'sequences': len(results), 'order_checks': checks, 'suffixes': len(suffixes)})
