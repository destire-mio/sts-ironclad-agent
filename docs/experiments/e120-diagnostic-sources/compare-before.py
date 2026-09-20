"""Replay each original power-order sequence from its initial fixture without resync."""
from pathlib import Path
import hashlib
import json
import os
import sys

Q = Path(__file__).resolve().parent
A = Q.parents[1]
S = A / 'evidence/e116-bomb-instance-repair-20260920-01/candidate'
os.environ['ALIGNMENT_BUILD'] = str(S / 'engine')
os.environ['ALIGNMENT_STRICT'] = '1'
assert os.environ.get('ALIGNMENT_REIMPORT') != '1'
sys.path.insert(0, str(A / 'tests'))
import compare_sequences as C

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
source = Q / 'original-controls/attempt-01/results.json'
rows = json.loads(source.read_text())
assert all(row['status'] == 'executed' for row in rows)
assert sha(C.sts.__file__) == json.loads((S / 'identity.json').read_text())['engine_sha256']
results = [C.compare_sequence(row) for row in rows]
proof = {'status': 'confirmed_difference' if any(r['status'] == 'mismatch' for r in results) else 'matched',
    'results': results, 'source_sha256': sha(source), 'engine_sha256': sha(C.sts.__file__),
    'checker_sha256': sha(__file__), 'comparison_driver_sha256': sha(C.__file__),
    'fixture_imports': len(rows), 'mid_sequence_resynchronized': False,
    'limits': 'One import before each controlled original sequence; all subsequent actual cards/end-turn actions execute without resynchronization. Not a natural seed or learned result.'}
with (Q / 'original-before-comparison.json').open('x') as f:
    json.dump(proof, f, indent=2); f.write('\n')
print([{'name': r['name'], 'status': r['status'],
    'differences': [{'step': i, 'fields': list(s['differences'])}
        for i, s in enumerate(r['steps']) if s['differences']]} for r in results])
