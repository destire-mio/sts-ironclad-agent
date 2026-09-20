"""Additional terminal RNG gate, derived from the E121 natural-start verifier."""
from pathlib import Path
import gzip, hashlib, json, sys
A = Path(__file__).resolve().parents[3] / 'ironclad-alignment'
sys.path.insert(0, str(A / 'tests'))
import compare_cards as C
from replay_run import outside_differences
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()

def compare_rng(native, actual):
    names = sorted(set(native) & set(actual))
    assert len(names) == 12 and set(native) - set(names) == {'mapRng'}
    return {name: {'original': C.bridge.rng_snapshot(native[name]), 'simulator': actual[name]}
            for name in names if C.bridge.rng_snapshot(native[name]) != actual[name]}

def audit(root, runtime, seed):
    root, runtime = Path(root), Path(runtime)
    assert sha(Path(C.sts.__file__)) == sha(runtime / 'engine/slaythespire.cpython-312-darwin.so')
    native = root / f'original/{seed}-01'
    result = json.loads((native / 'result.json').read_text())
    assert result['status'] == 'original_heart_trace_matched'
    rows = [json.loads(line) for line in gzip.decompress((native / 'rpc.jsonl.gz').read_bytes()).decode().splitlines()]
    trace_path = root / f'traces/{seed}.json'
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
    differences.update(compare_rng(view['rng'], gc.rng_states))
    proof = {'status': 'matched' if not differences else 'mismatch', 'seed': seed,
             'engine_sha256': sha(Path(C.sts.__file__)), 'script_sha256': sha(Path(__file__)),
             'trace_sha256': sha(trace_path), 'rpc_sha256': sha(native / 'rpc.jsonl.gz'),
             'natural_actions': actions, 'rng_streams': names, 'differences': differences,
             'state_imports': 0, 'resynchronized': False,
             'limits': 'Twelve exported simulator/original RNG streams at the common terminal. Native mapRng is not exported as a simulator state; map contents remain covered by the frozen live comparator.'}
    return proof
