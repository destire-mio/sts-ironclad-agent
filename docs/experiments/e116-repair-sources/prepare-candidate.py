"""Freeze E116 natural integration of the preselected E111 Heart route."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil

Q = Path(__file__).resolve().parent
S = Q.parent / 'e111-post-victory-exhaust-repair-20260920-01/candidate'
C = Q / 'candidate'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')

assert '100% tests passed out of 262' in (Q / 'ctest-full.log').read_text()
assert '100% tests passed out of 30' in (Q / 'portable-ctest-v2.log').read_text()
for name in ('original-after.json', 'portable-original-after.json'):
    proof = read(Q / name)
    assert proof['status'] == 'matched' and len(proof['results']) == 4
    assert len(proof['snapshot_suffixes']) == 15 and proof['wrong_multiplicity_rejected']
    assert proof['instance_checker_sha256'] == sha(Q / 'bomb_instances.py')
for name, expected in read(S / 'manifest.json')['frozen_files'].items():
    assert sha(S / name) == expected, name
for name, expected in read(Q / 'portable-application.json')['source_files'].items():
    assert sha(Q / 'source' / name) == sha(Q / 'portable-source-v2' / name) == expected
C.mkdir()
names = [n for n in read(S / 'manifest.json')['frozen_files']
         if n.startswith('source/') or n == 'model.pt']
names += ['heart_branch_pilot.py', 'heart_branch_training.py', 'heart_combat_development.py',
          'heart_play_selected.py', 'run_refresh.py', 'config.json', 'seeds.json']
for name in names:
    target = C / name; target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(S / name, target)
assert read(C / 'seeds.json') == {'fit': [], 'label_holdout': [], 'train_development': [1138994370]}
(C / 'engine').mkdir()
engine = C / 'engine/slaythespire.cpython-312-darwin.so'
shutil.copyfile(Q / 'build' / engine.name, engine)
write(C / 'identity.json', {'engine_sha256': sha(engine), 'model_sha256': sha(C / 'model.pt')})
write(C / 'plan.json', {
    'experiment': 'E116-integration', 'created_at': datetime.now(timezone.utc).isoformat(),
    'repair_plan_sha256': sha(Q / 'plan.json'), 'source_runtime': str(S),
    'source_manifest_sha256': sha(S / 'manifest.json'),
    'selection': '1138994370 was fixed in the E116 plan before repaired outcomes; no replacement.',
    'long_job_observation_interval_seconds': 1200,
    'verification': 'Natural parent NN/MCTS, all outside choices and state/RNG audited; repeat winner; original route; additive Bomb-instance checks; twelve terminal RNGs.',
    'limits': 'One known development route for integration. No labels, optimizer or unseen evaluation. E112 remains stopped.'})
shutil.copyfile(__file__, C / 'preparation-source.py')
write(C / 'manifest.json', {'frozen_files': {str(p.relative_to(C)): sha(p)
    for p in sorted(C.rglob('*')) if p.is_file()}})
print(read(C / 'identity.json'))
