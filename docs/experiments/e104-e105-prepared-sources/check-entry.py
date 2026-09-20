"""Check E104's gated entry and replay one already verified E102 source."""
from pathlib import Path
import ast, hashlib, importlib.util, json, sys

C = Path(__file__).resolve().parent
N = C.parent / 'heart-e102-scale-source-refresh-20260920-01'
R = C.parents[1]
S = R.parent / 'ironclad-alignment/evidence/e102-spot-weakness-intent-repair-20260920-01/candidate'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())
spec = importlib.util.spec_from_file_location('e104_collector', C / 'run_collections.py')
collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
for name, digest in read(C / 'registration.json')['hashes'].items():
    assert sha(C / name) == digest
try:
    collector.source_ready(C)
except FileNotFoundError as error:
    assert Path(error.filename) == N / 'natural/completion-verification.json'
else:
    raise AssertionError('source gate unexpectedly accepted incomplete natural sources')
assert not (C / 'relic-source').exists() and not (C / 'joint').exists()
E, I, D = collector.load(C, N / 'natural')
identity = read(C / 'protocol.json')['identity']
assert sha(E.R.sts.__file__) == identity['engine_sha256']
assert Path(E.R.sts.__file__).parent == N / 'natural/engine'
for name, values in read(C / 'source-copy-verification.json')['files'].items():
    path = C / 'frozen' / name
    assert sha(path) == values['after_sha256']
    source = path.read_text()
    for before, after in reversed(values['changes']):
        assert source.count(after) == 1
        source = source.replace(after, before)
    assert hashlib.sha256(source.encode()).hexdigest() == values['before_sha256']
    ast.parse(path.read_text())
E.S.verify_files(S)
assert read(S / 'identity.json') == identity
path = S / 'episodes/192246470.json.gz'
row = E.H.read_json(path)
config = read(S / 'config.json')
model = E.H.load_scorer(E.H.torch.load(S / 'model.pt', weights_only=True, map_location='cpu'))
node = E.B.first_root(row, path, 'train_development', config, model)
assert node is not None and node['seed'] == 192246470
assert node['chosen'] in node['candidates'] and node['source_sha256'] == sha(path)
gc = E.R.replay(row['seed'], row['prefix'][:node['prefix_index']], config)
assert E.R.fingerprint(gc) == node['fingerprint']
assert gc.act == 1 and gc.screen_state == E.R.sts.ScreenState.BOSS_RELIC_REWARDS
output = {
    'status': 'complete', 'registration_sha256': sha(C / 'registration.json'),
    'checker_sha256': sha(Path(__file__)), 'incomplete_natural_source_rejected': True,
    'formal_destination_directories_absent': True, 'runtime_identity': identity,
    'frozen_modules_checked': 15, 'deadline_only_module_changes_checked': 3,
    'known_E102_source_replay': {'seed': row['seed'], 'episode_sha256': sha(path),
        'prefix_index': node['prefix_index'], 'candidates': node['candidates'], 'chosen': node['chosen'],
        'natural_public_state_reconstructed': True},
    'new_mcts_calls': 0, 'new_continuation_labels': 0, 'optimizer_updates': 0,
    'limits': 'Entry and known-source replay controls only; full source admission and new label generation remain pending.'}
with (C / 'entry-verification.json').open('x') as f:
    json.dump(output, f, indent=2); f.write('\n')
print(output)
