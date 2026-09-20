"""Register the scoped E120 repair before editing a copied E116 source tree."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil

Q = Path(__file__).resolve().parent
A = Q.parents[1]
S = Q.parent / 'e116-bomb-instance-repair-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
files = {str(p.relative_to(S / 'source')): sha(p)
         for p in sorted((S / 'source').rglob('*')) if p.is_file()}
assert len(files) == 90
assert all(sha(A / 'simulator' / n) == h for n, h in files.items())
plan = {
    'experiment': 'E121', 'registered_at': datetime.now(timezone.utc).isoformat(),
    'diagnosis': 'E120 controlled original Combust / No Draw / Runic Cube mismatch',
    'diagnosis_sha256': sha(Q.parent / 'e120-end-turn-order-diagnostic-20260920-01/original-before-comparison.json'),
    'before_source': str(S / 'source'), 'before_source_files': files,
    'before_engine_sha256': sha(S / 'candidate/engine/slaythespire.cpython-312-darwin.so'),
    'change': 'Store native priority order with stable acquisition ties. Stacking keeps position; removal and reapplication change position. Every Bomb retains its identity in the same ordered list. Preserve state across templates, snapshots, value copies and printing; use order in existing turn callbacks.',
    'checks': ['same C++ behavioral cases on E116 and repaired source',
               'four recorded E120 original sequences, no mid-sequence resync',
               'ordered snapshot and clone suffixes; wrong-order negative control',
               'E116 Bomb sequences and regression controls',
               'complete CTest and clean portable patch source-hash verification',
               'fixed development integration seed 1138994370 with parent NN and MCTS, original replay and RNG evidence'],
    'selected_integration_seed': 1138994370,
    'long_job_observation_interval_seconds': 1200,
    'training_collection_permitted_before_validation': False,
    'limits': 'Player turn callback ordering, not a claim of all game hooks being aligned. E117 stopped; E118/E119 closed. No new model, labels, optimization or unseen acceptance in this repair.'}
with (Q / 'plan.json').open('x') as f:
    json.dump(plan, f, indent=2); f.write('\n')
shutil.copytree(S / 'source', Q / 'source')
print({'registered': 'E121', 'copied_source_files': len(files)})
