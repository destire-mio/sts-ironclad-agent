"""Freeze a new-engine parent-route choice probe; no branch labels or fitting."""
from pathlib import Path
import hashlib, json, shutil

Q = Path(__file__).resolve().parent
R = Q.parents[1]
C = Q.parent / 'heart-e116-scale-joint-labels-20260920-01'
S = R.parent / 'ironclad-alignment/evidence/e116-bomb-instance-repair-20260920-01/candidate'
P = Q / 'native-probe'; P.mkdir()
N = P / 'runtime'; N.mkdir()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())
for name, digest in read(S / 'manifest.json')['frozen_files'].items():
    assert sha(S / name) == digest
    if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json', 'identity.json'):
        destination = N / name; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(S / name, destination)
for path in (C / 'frozen').glob('*.py'):
    shutil.copyfile(path, N / path.name)
for name in ('heart_relic_card_model.py', 'heart_contextual_relic.py', 'heart_relic_card_readout.py'):
    shutil.copyfile(C / 'frozen' / name, N / 'source' / name)
loader = N / 'source/heart_train.py'
text, marker = loader.read_text(), 'def load_scorer(checkpoint):\n'
assert text.count(marker) == 1 and 'joint_frozen_readout' not in text
loader.write_text(text.replace(marker, marker +
    '    if checkpoint.get("model_type") == "joint_first_relic_card":\n'
    '        from heart_relic_card_model import RelicCardPolicy\n'
    '        return RelicCardPolicy(checkpoint).eval()\n'
    '    if checkpoint.get("model_type") == "joint_frozen_readout":\n'
    '        from heart_relic_card_readout import ReadoutPolicy\n'
    '        return ReadoutPolicy(checkpoint).eval()\n'))
manifest = {'frozen_files': {str(p.relative_to(N)): sha(p) for p in N.rglob('*') if p.is_file()}}
(N / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
(P / 'plan.json').write_text(json.dumps({
    'known_source': str(S), 'source_manifest_sha256': sha(S / 'manifest.json'),
    'episode': str(S / 'episodes/1138994370.json.gz'),
    'episode_sha256': sha(S / 'episodes/1138994370.json.gz'),
    'runtime_manifest_sha256': sha(N / 'manifest.json'),
    'collector_registration_sha256': sha(C / 'registration.json'),
    'scope': 'Two zero-head readout models on the one observed E116 parent relic/card path; use only its observed parent terminal, no counterfactual labels or complete-tree claim. Positive native choices plus wrong-expanded-relic/card expectation rejections. No MCTS or optimizer updates.'}, indent=2) + '\n')
print({'prepared': str(P), 'runtime_manifest_sha256': sha(N / 'manifest.json')})
