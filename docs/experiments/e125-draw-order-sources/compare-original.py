"""Replay observed card commands once; compare persistent draw effects at victory too."""
from pathlib import Path
import copy
import hashlib
import json
import os
import sys

Q = Path(__file__).resolve().parent
A = Q.parents[1]
S = Q.parent / 'e121-power-order-repair-20260920-01/candidate'
os.environ['ALIGNMENT_BUILD'] = str(S / 'engine')
assert os.environ.get('ALIGNMENT_REIMPORT') != '1'
sys.path.insert(0, str(A / 'tests'))
import compare_cards as C
import compare_powers as P

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())


def compare(row):
    assert row['status'] == 'executed'
    game = copy.deepcopy(row['before']['game'])
    game['combat_state']['rngs'] = {key: row['before']['rng'][name] for key, name in C.RNG_NAMES.items()}
    battle = C.sts.BattleContext.from_snapshot(C.bridge.build_snapshot(game), 123)
    steps = []
    for step in row['trace']:
        words = step['command'].split()
        assert words[0] == 'play' and len(words) == 2
        action = C.sts.SearchAction(C.sts.SearchActionType.CARD, int(words[1]) - 1, 0)
        assert action.is_valid(battle), step['command']
        action.execute(battle)
        view = step['after']
        expected = {'shuffle': C.bridge.rng_snapshot(view['rng']['shuffleRng']),
            'sundial': next(r['counter'] for r in view['game']['relics'] if r['id'] == 'Sundial')}
        actual = {'shuffle': battle.rng_states['shuffle'], 'sundial': battle.snapshot_counters['sundial']}
        if view['game']['room_phase'] == 'COMBAT' and view['game']['screen_type'] == 'NONE':
            expected.update(C.original(view['game']))
            actual.update(C.simulator(battle))
            expected['rng'] = {key: C.bridge.rng_snapshot(view['rng'][name]) for key, name in C.RNG_NAMES.items()}
            actual['rng'] = battle.rng_states
        differences = {key: {'original': expected[key], 'simulator': actual[key]}
            for key in expected if expected[key] != actual[key]}
        if view['game']['room_phase'] == 'COMBAT' and view['game']['screen_type'] == 'NONE':
            differences.update(P.extras(view['game'], battle))
        steps.append({'command': step['command'], 'differences': differences})
    return {'name': row['spec']['name'], 'steps': steps,
        'status': 'mismatch' if any(s['differences'] for s in steps) else 'passed'}


if __name__ == '__main__':
    source = Q / 'original-controls/attempt-01/results.json'
    rows = read(source)
    assert len(rows) == 4 and all(r['status'] == 'executed' for r in rows)
    assert sha(C.sts.__file__) == read(S / 'identity.json')['engine_sha256']
    results = [compare(row) for row in rows]
    proof = {'status': 'confirmed_difference' if any(r['status'] == 'mismatch' for r in results) else 'matched',
        'results': results, 'source_sha256': sha(source), 'engine_sha256': sha(C.sts.__file__),
        'checker_sha256': sha(__file__), 'legacy_comparator_sha256': sha(C.__file__),
        'fixture_imports': 4, 'mid_sequence_resynchronized': False,
        'terminal_scope': 'At victory compare shuffle RNG counter/internal state and Sundial. Reward-generation RNG is not compared with an unexited battle. All six battle streams and core state are compared while both remain in combat.',
        'limits': 'Controlled A20 Ironclad sequences, not natural seed or learned result.'}
    with (Q / 'original-before-comparison.json').open('x') as stream:
        json.dump(proof, stream, indent=2)
        stream.write('\n')
    print([{'name': r['name'], 'status': r['status'],
        'differing_steps': [s for s in r['steps'] if s['differences']]} for r in results])
