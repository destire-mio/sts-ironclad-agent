"""Original sequences plus independent Bomb state/import/clone checks."""
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
import bomb_instances as B

sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
legacy_extras = P.extras
checks = 0
def extras(game, battle):
    global checks
    checks += 1
    return {**legacy_extras(game, battle), **B.differences(game, battle)}
P.extras = extras

source = Q.parent / 'e115-bomb-instance-diagnostic-20260920-01/original-controls/attempt-01/results.json'
rows = json.loads(source.read_text())
assert len(rows) == 4 and all(row['status'] == 'executed' for row in rows)
results = [C.compare_sequence(row) for row in rows]
assert all(r['status'] == 'passed' for r in results), results

def imported(view):
    game = copy.deepcopy(view['game'])
    game['combat_state']['rngs'] = {k: view['rng'][v] for k, v in C.RNG_NAMES.items()}
    return C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)

def state_difference(view, battle):
    wanted, got = C.original(view['game']), C.simulator(battle)
    wanted['rng'] = {k: C.bridge.rng_snapshot(view['rng'][v]) for k, v in C.RNG_NAMES.items()}
    got['rng'] = battle.rng_states
    return {**{k: {'original': wanted[k], 'simulator': got[k]} for k in wanted if wanted[k] != got[k]},
            **extras(view['game'], battle)}

def execute(battle, command):
    words = command.split()
    if words[0] == 'end':
        action = C.sts.SearchAction(C.sts.SearchActionType.END_TURN)
    else:
        assert words[0] == 'play'
        action = C.sts.SearchAction(C.sts.SearchActionType.CARD, int(words[1]) - 1, 0)
    assert action.is_valid(battle)
    action.execute(battle)

restorations = []
for row in rows:
    for index, step in enumerate(row['trace']):
        if not B.expected(step['after']['game']):
            continue
        b = imported(step['after'])
        assert not state_difference(step['after'], b), (row['spec']['name'], index, state_difference(step['after'], b))
        sibling = b.clone()
        initial = B.actual(sibling)
        checks_at_start = checks
        for later in row['trace'][index + 1:]:
            execute(b, later['command'])
            assert not state_difference(later['after'], b), (row['spec']['name'], index, later['command'], state_difference(later['after'], b))
        assert B.actual(sibling) == initial, 'sibling changed with the first branch'
        for later in row['trace'][index + 1:]:
            execute(sibling, later['command'])
            assert not state_difference(later['after'], sibling)
        assert C.simulator(b) == C.simulator(sibling) and B.actual(b) == B.actual(sibling)
        restorations.append({'case': row['spec']['name'], 'after_action': index,
                             'independent_suffix_checks': checks - checks_at_start})

# Equal aggregate damage must not hide an instance-count difference.
base = copy.deepcopy(rows[-1]['trace'][2]['after']['game'])
base['combat_state']['player']['powers'] = [
    {'id': f'TheBomb{i}', 'amount': 3, 'damage': 40} for i in range(5)]
snapshot = C.bridge.build_snapshot(base)
b = C.sts.BattleContext.from_snapshot(snapshot, 123)
assert list(b.player.bombs) == [0, 0, 200] and not B.differences(base, b)
tampered = copy.deepcopy(base)
tampered['combat_state']['player']['powers'] = [
    {'id': f'TheBomb{i}', 'amount': 3, 'damage': 50} for i in range(4)]
assert B.differences(tampered, b), 'equal-total wrong multiplicity was accepted'
for bad in ('missing', 'zero'):
    malformed = copy.deepcopy(snapshot)
    if bad == 'missing': del malformed['player']['powers'][0]['bomb_turns']
    else: malformed['player']['powers'][0]['bomb_turns'] = 0
    try:
        C.sts.BattleContext.from_snapshot(malformed, 123)
    except ValueError:
        pass
    else:
        raise AssertionError('malformed Bomb countdown was accepted')

proof = {'status': 'matched', 'engine_sha256': sha(C.sts.__file__), 'source_sha256': sha(source),
         'checker_sha256': sha(__file__), 'instance_checker_sha256': sha(B.__file__),
         'sequence_driver_sha256': sha(C.__file__), 'legacy_power_checker_sha256': sha(P.__file__),
         'results': results, 'instance_comparisons': checks, 'snapshot_suffixes': restorations,
         'wrong_multiplicity_rejected': True, 'missing_and_zero_countdowns_rejected': True,
         'sequence_initial_imports': len(rows), 'mid_sequence_resynchronized': False,
         'limits': 'Four controlled original sequences, plus separately declared snapshot/clone continuations. No natural-seed or learning claim.'}
with args.out.open('x') as f: json.dump(proof, f, indent=2); f.write('\n')
print({'status': proof['status'], 'sequences': len(results), 'instance_comparisons': checks,
       'snapshot_suffixes': len(restorations)})
