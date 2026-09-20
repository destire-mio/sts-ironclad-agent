"""Register E117 only after E116 repair completion; do not launch source workers."""
from pathlib import Path
from datetime import datetime, timezone
import ast
import copy
import hashlib
import json
import shutil
import subprocess
import sys

R = Path(__file__).resolve().parents[1]
A = R.parent / 'ironclad-alignment'
OLD = R / 'runs/heart-e111-scale-source-refresh-20260920-01'
OLD_Q = A / 'evidence/e112-development-parity-20260920-01'
REPAIR = A / 'evidence/e116-bomb-instance-repair-20260920-01'
N = R / 'runs/heart-e116-scale-source-refresh-20260920-01'
Q = A / 'evidence/e117-development-parity-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')
def rebound(text):
    for old, new in [(str(OLD), str(N)), (OLD.name, N.name), (str(OLD_Q), str(Q)),
                     (OLD_Q.name, Q.name), ('E112', 'E117'), ('e112', 'e117'),
                     ('E111', 'E116'), ('e111-post-victory-exhaust-repair', 'e116-bomb-instance-repair')]:
        text = text.replace(old, new)
    return text
def script(source, target, changes=()):
    text = rebound(source.read_text())
    for before, after in changes:
        assert text.count(before) == 1, (source, before)
        text = text.replace(before, after)
    ast.parse(text)
    with target.open('x') as f: f.write(text)

# Fail before any successor directory exists if the scoped repair is incomplete.
proof = read(REPAIR / 'completion-verification.json')
assert proof['status'] == 'complete' and proof['source_refresh_permitted']
for name, expected in proof['hashes'].items(): assert sha(REPAIR / name) == expected, name
assert not N.exists() and not Q.exists()
N.mkdir(); Q.mkdir()
protocol = copy.deepcopy(read(OLD / 'protocol.json'))
protocol.update(experiment='E117', created_at=datetime.now(timezone.utc).isoformat(),
    question='Regenerate the unchanged 6144 families under E116 before joint relic/card data-scale training. E115 Bomb multiplicity is repaired; the data-scale hypothesis remains untested.',
    source_runtime=str(REPAIR / 'candidate'), source_manifest_sha256=sha(REPAIR / 'candidate/manifest.json'),
    repair_completion=str(REPAIR / 'completion-verification.json'),
    repair_completion_sha256=sha(REPAIR / 'completion-verification.json'),
    repair_publication_sha256=sha(REPAIR / 'publication-verification.json'),
    previous_source_stop_sha256=sha(OLD / 'stop-verification.json'),
    limits='Known-family source renewal after E116, not a learned gain or unseen acceptance. E112/E113/E114 stay closed. Source outcomes and all downstream labels must use E116.')
protocol['scope']['engine_sha256'] = proof['engine_sha256']
protocol['gates'] = [rebound(value) for value in protocol['gates']]
protocol['gates'][1] += ' Compare every Bomb instance in both live and recorded native replays; aggregate power totals do not satisfy this gate.'
write(N / 'protocol.json', protocol)
script(OLD / 'prepare_source.py', N / 'prepare_source.py')
write(N / 'registration.json', {'hashes': {name: sha(N / name) for name in ('protocol.json', 'prepare_source.py')}})
subprocess.run([sys.executable, N / 'prepare_source.py'], check=True)
assert sha(N / 'seeds.json') == sha(OLD / 'seeds.json')
assert sha(N / 'family-groups.json') == sha(OLD / 'family-groups.json')

live_change = '''    loaded = V.setup(ROOT)
    import bomb_extras as B
    loaded[-1].extras = B.extras
    original = V.one(ROOT, seed, 1, loaded)
    live_checks, live_bearing = B.checks, B.bomb_bearing_checks'''
recorded_change = '''        recorded = M.run(recorded_root)
        instance_proof = {'status': 'matched' if recorded['status'] == 'recorded_original_heart_trace_matched' else 'failed',
            'seed': seed, 'engine_sha256': reg['identity']['engine_sha256'],
            'combiner_sha256': sha(ROOT / 'bomb_extras.py'), 'instance_checker_sha256': sha(ROOT / 'bomb_instances.py'),
            'live_checks': live_checks, 'recorded_checks': B.checks - live_checks,
            'live_bomb_bearing_checks': live_bearing, 'recorded_bomb_bearing_checks': B.bomb_bearing_checks - live_bearing,
            'trace_sha256': sha(trace), 'rpc_sha256': sha(native / 'rpc.jsonl.gz'),
            'state_imports': 0, 'resynchronized': False}
        write(ROOT / f'bomb-instances/{seed}.json', instance_proof)
        result['bomb_instances'] = instance_proof'''
verified_change = '''                instance_proof = read(ROOT / f"bomb-instances/{result['seed']}.json")
                assert instance_proof == result['bomb_instances'] and instance_proof['status'] == 'matched'
                assert instance_proof['live_checks'] > 0 and instance_proof['recorded_checks'] > 0
                assert instance_proof['seed'] == result['seed'] and instance_proof['engine_sha256'] == reg['identity']['engine_sha256']
                assert instance_proof['combiner_sha256'] == sha(ROOT / 'bomb_extras.py')
                assert instance_proof['instance_checker_sha256'] == sha(ROOT / 'bomb_instances.py')
                assert instance_proof['state_imports'] == 0 and instance_proof['resynchronized'] is False
                assert instance_proof['trace_sha256'] == sha(ROOT / f"traces/{result['seed']}.json")
                assert instance_proof['rpc_sha256'] == sha(ROOT / f"original/{result['seed']}-01/rpc.jsonl.gz")
                verified.append(checked)'''
script(OLD_Q / 'cohort.py', Q / 'cohort.py', [
    ('    original = V.one(ROOT, seed, 1, V.setup(ROOT))', live_change),
    ('        recorded = M.run(recorded_root)', recorded_change),
    ('                verified.append(checked)', verified_change),
    ("            'terminal_rng_streams_per_route': 12,", "            'terminal_rng_streams_per_route': 12, 'bomb_instance_comparison_required': True,")])
for name in ('bomb_instances.py', 'bomb_extras.py'):
    shutil.copyfile(REPAIR / name, Q / name)
shutil.copyfile(OLD_Q / 'terminal_rng.py', Q / 'terminal_rng.py')
reg = copy.deepcopy(read(OLD_Q / 'registration.json'))
reg.update(experiment='E117P', created_at=datetime.now(timezone.utc).isoformat(), source=str(N / 'natural'),
    source_manifest_sha256=sha(N / 'natural/manifest.json'), source_roles_sha256=sha(N / 'natural/seeds.json'),
    parent_registration_sha256=sha(N / 'registration.json'), identity=read(N / 'natural/identity.json'),
    reuse_source_cohort_sha256=sha(OLD_Q / 'cohort.py'))
reg['selection'] = rebound(reg['selection'])
reg['verification'] = rebound(reg['verification']) + ' Add independent, per-instance Bomb state checks to both live and recorded comparisons.'
reg.pop('changes_from_E107', None)
reg['changes_from_E112'] = 'Renew source bindings after E116; add per-instance Bomb comparisons and proof metadata. Preserve native state/RNG comparators, role split, winner scope and budgets.'
reg['harness_sha256'] = {rebound(name): sha(Path(rebound(name))) for name in reg['harness_sha256']}
for name in ('bomb_instances.py', 'bomb_extras.py'):
    reg['harness_sha256'][str(Q / name)] = sha(Q / name)
write(Q / 'registration.json', reg)
script(OLD / 'check-entry.py', N / 'check-entry.py')
subprocess.run([sys.executable, N / 'check-entry.py'], check=True)
shutil.copyfile(__file__, N / 'preparation-source.py')
write(N / 'preparation-bindings.json', {
    'status': 'prepared_not_launched', 'source': str(OLD), 'source_original_gate': str(OLD_Q),
    'repair_proof_sha256': sha(REPAIR / 'completion-verification.json'),
    'source_registration_sha256': sha(N / 'registration.json'), 'original_registration_sha256': sha(Q / 'registration.json'),
    'role_files_byte_identical': True, 'new_MCTS_calls': 0, 'new_optimizer_updates': 0,
    'limits': 'Source/import gates prepared. Execution wrapper and Bomb-gate controls must pass before launch.'})
print({'prepared': str(N), 'original_gate': str(Q), 'not_launched': True})
