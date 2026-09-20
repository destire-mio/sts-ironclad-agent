"""Register six additional persistent-RNG checks of the complete original run."""
from pathlib import Path
import hashlib, json
Q = Path(__file__).resolve().parent
A = Q.parents[1]
N = Q / 'candidate-original'
C = Q / 'candidate'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())
plan = read(N / 'plan.json'); seed = 1138994370
native = N / f'original/{seed}-01'
result = read(native / 'result.json')
expected = 'original_heart_trace_matched' if plan['expected_terminal_status'] == 'heart_win' else 'original_death_trace_matched'
assert result['status'] == expected and read(native / 'cleanup.json')['remaining'] == []
paths = [native / p for p in ('result.json', 'identity.json', 'cleanup.json', 'rpc.jsonl.gz', 'comparisons.json')]
paths += [N / f'traces/{seed}.json', C / 'config.json']
child = dict(plan, comparison_driver_sha256=sha(A / 'tests/verify_heart_winners.py'),
             recorded_driver_sha256=sha(A / 'tests/replay_recorded_winner.py'),
             reference_original=str(native), reference_trace=str(N / f'traces/{seed}.json'),
             reference_runtime_config=str(C / 'config.json'),
             reference_hashes={str(p): sha(p) for p in paths}, regression_only=False)
dest = N / 'recorded'; dest.mkdir()
with (dest / 'plan.json').open('x') as f:
    json.dump(child, f, indent=2); f.write('\n')
