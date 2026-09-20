"""Compare twelve exported RNG streams at the fresh original terminal, from a natural start."""
from pathlib import Path
import gzip, hashlib, json, sys
Q = Path(__file__).resolve().parent
A = Q.parents[1]
sys.path.insert(0, str(A / 'tests'))
import compare_cards as C
from replay_run import outside_differences
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
seed = 1138994370
native = Q / f'candidate-original/original/{seed}-01'
result = json.loads((native / 'result.json').read_text())
assert result['status'] == 'original_heart_trace_matched'
rows = [json.loads(line) for line in gzip.decompress((native / 'rpc.jsonl.gz').read_bytes()).decode().splitlines()]
trace_path = Q / f'candidate-original/traces/{seed}.json'
trace = json.loads(trace_path.read_text())
gc = C.sts.GameContext(C.sts.CharacterClass.IRONCLAD, seed, 20)
actions = 0
for step in trace['steps']:
    gc.set_play_time(step['play_time_seconds'])
    assert (gc.floor_num, int(gc.screen_state)) == (step['floor'], step['screen'])
    if step['screen'] == 9:
        b = C.sts.BattleContext(); b.init(gc)
        for bits in step['actions']:
            action = C.sts.SearchAction.from_bits(bits & 0xffffffff)
            assert action.is_valid(b); action.execute(b); actions += 1
        assert b.outcome != C.sts.Outcome.UNDECIDED
        b.exit_battle(gc)
    else:
        for bits in step['actions']:
            action = C.sts.GameAction(bits & 0xffffffff)
            assert action.is_valid(gc); action.execute(gc); actions += 1
view = rows[-1]['response']['result']
assert view['game']['screen_type'] == 'GAME_OVER' and view['game']['screen_state']['victory']
assert gc.outcome == C.sts.GameOutcome.PLAYER_VICTORY
differences = outside_differences(view, gc)
names = sorted(set(view['rng']) & set(gc.rng_states))
assert len(names) == 12 and set(view['rng']) - set(names) == {'mapRng'}
for name in names:
    wanted = C.bridge.rng_snapshot(view['rng'][name]); actual = gc.rng_states[name]
    if wanted != actual: differences[name] = {'original': wanted, 'simulator': actual}
proof = {'status': 'matched' if not differences else 'mismatch', 'seed': seed,
         'engine_sha256': sha(Path(C.sts.__file__)), 'script_sha256': sha(Path(__file__)),
         'trace_sha256': sha(trace_path), 'rpc_sha256': sha(native / 'rpc.jsonl.gz'),
         'natural_actions': actions, 'rng_streams': names, 'differences': differences,
         'state_imports': 0, 'resynchronized': False,
         'limits': 'Twelve exported simulator/original RNG streams at the common terminal. Native mapRng is not exported as a simulator state; map contents remain covered by the frozen live comparator.'}
with (Q / 'terminal-rng-verification.json').open('x') as f: json.dump(proof, f, indent=2); f.write('\n')
print({k: v for k, v in proof.items() if k != 'limits'})
assert not differences
