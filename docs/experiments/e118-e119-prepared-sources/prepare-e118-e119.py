"""Renew the unexecuted joint-decision scale study under the E116 engine."""
from pathlib import Path
from datetime import datetime, timezone
import ast
import hashlib
import json
import shutil

R = Path(__file__).resolve().parents[1]
A = R.parent / 'ironclad-alignment'
OC = R / 'runs/heart-e111-scale-joint-labels-20260920-01'
OT = R / 'runs/heart-e111-scale-training-20260920-01'
C = R / 'runs/heart-e116-scale-joint-labels-20260920-01'
T = R / 'runs/heart-e116-scale-training-20260920-01'
N = R / 'runs/heart-e116-scale-source-refresh-20260920-01'
Q = A / 'evidence/e117-development-parity-20260920-01'
S = A / 'evidence/e116-bomb-instance-repair-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
created = datetime.now(timezone.utc).isoformat()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


common = [
    ['heart-e111-scale-source-refresh-20260920-01', N.name],
    [OC.name, C.name], [OT.name, T.name],
    ['e112-development-parity-20260920-01', Q.name],
    ['e111-post-victory-exhaust-repair-20260920-01', S.name],
    ['E114', 'E119'], ['E113', 'E118'], ['E112', 'E117'], ['E111', 'E116'],
    ['e114', 'e119'], ['e113', 'e118'], ['e112', 'e117'],
]


def rebound(text):
    for before, after in common:
        text = text.replace(before, after)
    return text


changes = {}


def copy(source, destination, extra=(), bindings=True):
    replacements = list(common if bindings else []) + list(extra)
    text = source.read_text()
    for index, (before, after) in enumerate(replacements):
        if index >= (len(common) if bindings else 0):
            assert before in text, (source.name, before[:100])
        text = text.replace(before, after)
    ast.parse(text)
    with destination.open('x') as stream:
        stream.write(text)
    changes[str(destination)] = {'source': str(source), 'before_sha256': sha(source),
        'after_sha256': sha(destination), 'allowed_replacements': replacements}


def function(path, name):
    text = path.read_text()
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(text, node)


bomb_contract = '''
def require_bomb_instances(proof, identity, combiner_sha, checker_sha):
    assert proof['bomb_instance_comparison_required'] is True
    for row in proof['rows']:
        instance = row['bomb_instances']
        assert instance['status'] == 'matched' and instance['seed'] == row['seed']
        assert instance['engine_sha256'] == identity['engine_sha256']
        assert instance['combiner_sha256'] == combiner_sha
        assert instance['instance_checker_sha256'] == checker_sha
        for phase in ('live', 'recorded'):
            checks, bearing = instance[phase + '_checks'], instance[phase + '_bomb_bearing_checks']
            assert type(checks) is int and checks > 0
            assert type(bearing) is int and 0 <= bearing <= checks
        assert instance['state_imports'] == 0 and instance['resynchronized'] is False
        assert instance['trace_sha256'] == proof['hashes'][f"traces/{row['seed']}.json"]
        assert instance['rpc_sha256'] == proof['hashes'][f"original/{row['seed']}-01/rpc.jsonl.gz"]

'''


assert not C.exists() and not T.exists()
assert read(S / 'completion-verification.json')['status'] == 'complete'
identity = read(N / 'natural/identity.json')
assert identity['engine_sha256'] == read(S / 'completion-verification.json')['engine_sha256']
for root in (C, T):
    root.mkdir()
shutil.copytree(OC / 'frozen', C / 'frozen', ignore=shutil.ignore_patterns('__pycache__'))
shutil.copyfile(OC / 'source-copy-verification.json', C / 'source-copy-verification.json')
assert len(list((C / 'frozen').glob('*.py'))) == 15
assert all(sha(p) == sha(OC / 'frozen' / p.name) for p in (C / 'frozen').glob('*.py'))
copy(OC / 'run_collections.py', C / 'run_collections.py', [
    ['def source_ready(root):', bomb_contract + '\ndef source_ready(root):'],
    ["    require_terminal_rng(original, plan['identity'], plan['terminal_rng_helper_sha256'])\n",
     "    require_terminal_rng(original, plan['identity'], plan['terminal_rng_helper_sha256'])\n"
     "    assert sha(parity / 'bomb_extras.py') == plan['bomb_combiner_sha256']\n"
     "    assert sha(parity / 'bomb_instances.py') == plan['bomb_instance_checker_sha256']\n"
     "    require_bomb_instances(original, plan['identity'], plan['bomb_combiner_sha256'], plan['bomb_instance_checker_sha256'])\n"],
])
for name in ('check-entry.py', 'run_pipeline.py', 'check-launcher.py'):
    copy(OC / name, C / name)
cp = json.loads(rebound((OC / 'protocol.json').read_text()))
cp.update(created_at=created, identity=identity,
    source_manifest_sha256=sha(N / 'natural/manifest.json'),
    parity_registration_sha256=sha(Q / 'registration.json'),
    parent_registration_sha256=sha(N / 'registration.json'),
    inherited_collector_registration_sha256=sha(OC / 'registration.json'),
    terminal_rng_helper_sha256=sha(Q / 'terminal_rng.py'),
    bomb_combiner_sha256=sha(Q / 'bomb_extras.py'),
    bomb_instance_checker_sha256=sha(Q / 'bomb_instances.py'),
    source_gates=cp['source_gates'] + ' Each original route needs the frozen per-instance Bomb comparison in both live and recorded execution, linked to the same trace and RPC.',
    limits='Label preparation under E116 only until all E117 gates pass. E112/E113/E114 remain closed and inadmissible. The original scale hypothesis remains untested; no learned gain or unseen acceptance.')
write(C / 'protocol.json', cp)
write(C / 'registration.json', {'experiment': 'E118', 'created_at': created,
    'hashes': {str(p.relative_to(C)): sha(p) for p in sorted(C.rglob('*'))
        if p.is_file() and p.name not in ('check-entry.py', 'run_pipeline.py', 'check-launcher.py')}})

for name in ('scale_training.py', 'scale_verify.py', 'run-native-probe.py',
             'check-renewal-entry.py', 'prepare-native-probe.py', 'terminal_rng.py'):
    copy(OT / name, T / name)
for name in ('bomb_extras.py', 'bomb_instances.py'):
    copy(Q / name, T / name, bindings=False)
copy(OT / 'scale_development.py', T / 'scale_development.py', [
    ['def require_original_complete(proof, expected, identity, terminal_helper_sha):',
     bomb_contract + '\ndef require_original_complete(proof, expected, identity, terminal_helper_sha, bomb_combiner_sha, bomb_checker_sha):'],
    ['    require_terminal_rng(proof, identity, terminal_helper_sha)\n',
     '    require_terminal_rng(proof, identity, terminal_helper_sha)\n'
     '    require_bomb_instances(proof, identity, bomb_combiner_sha, bomb_checker_sha)\n'],
    ["        require_original_complete(proof, expected, report['identity'], sha(ROOT / 'terminal_rng.py'))\n",
     "        require_original_complete(proof, expected, report['identity'], sha(ROOT / 'terminal_rng.py'),\n"
     "                                  sha(ROOT / 'bomb_extras.py'), sha(ROOT / 'bomb_instances.py'))\n"],
])
one = function(Q / 'cohort.py', 'one')
for name in ('bomb_extras.py', 'bomb_instances.py'):
    one = one.replace(f"sha(ROOT / '{name}')", f"sha(G.ROOT / '{name}')")
copy(OT / 'candidate_original.py', T / 'candidate_original.py', [
    [function(OT / 'candidate_original.py', 'one'), one],
    ["                verified.append(checked)",
     "                instance_proof = read(ROOT / f\"bomb-instances/{result['seed']}.json\")\n"
     "                assert instance_proof == result['bomb_instances'] and instance_proof['status'] == 'matched'\n"
     "                assert instance_proof['live_checks'] > 0 and instance_proof['recorded_checks'] > 0\n"
     "                assert instance_proof['seed'] == result['seed'] and instance_proof['engine_sha256'] == reg['identity']['engine_sha256']\n"
     "                assert instance_proof['combiner_sha256'] == sha(G.ROOT / 'bomb_extras.py')\n"
     "                assert instance_proof['instance_checker_sha256'] == sha(G.ROOT / 'bomb_instances.py')\n"
     "                assert instance_proof['state_imports'] == 0 and instance_proof['resynchronized'] is False\n"
     "                assert instance_proof['trace_sha256'] == sha(ROOT / f\"traces/{result['seed']}.json\")\n"
     "                assert instance_proof['rpc_sha256'] == sha(ROOT / f\"original/{result['seed']}-01/rpc.jsonl.gz\")\n"
     "                verified.append(checked)"],
    ["            'terminal_rng_streams_per_route': 12,\n",
     "            'terminal_rng_streams_per_route': 12, 'bomb_instance_comparison_required': True,\n"],
])

positive_addition = '''    combiner_sha, checker_sha = 'fixture-bomb-combiner', 'fixture-bomb-checker'
    positive['bomb_instance_comparison_required'] = True
    for row in positive['rows']:
        row['bomb_instances'] = {
            'status': 'matched', 'seed': row['seed'], 'engine_sha256': identity['engine_sha256'],
            'combiner_sha256': combiner_sha, 'instance_checker_sha256': checker_sha,
            'live_checks': 7, 'recorded_checks': 7,
            'live_bomb_bearing_checks': 2, 'recorded_bomb_bearing_checks': 2,
            'trace_sha256': row['terminal_rng']['trace_sha256'], 'rpc_sha256': row['terminal_rng']['rpc_sha256'],
            'state_imports': 0, 'resynchronized': False}
    G.require_original_complete(positive, [11, 29], identity, helper_sha, combiner_sha, checker_sha)
'''
negative_addition = '''    for name, field, replacement in (
        ('bomb_status', 'status', 'mismatch'), ('bomb_seed', 'seed', 30),
        ('bomb_engine', 'engine_sha256', 'wrong-engine'),
        ('bomb_combiner', 'combiner_sha256', 'old-combiner'),
        ('bomb_checker', 'instance_checker_sha256', 'old-checker'),
        ('bomb_no_live_checks', 'live_checks', 0), ('bomb_no_recorded_checks', 'recorded_checks', 0),
        ('bomb_negative_bearing', 'live_bomb_bearing_checks', -1),
        ('bomb_impossible_bearing', 'recorded_bomb_bearing_checks', 8),
        ('bomb_import', 'state_imports', 1), ('bomb_resync', 'resynchronized', True),
        ('bomb_trace', 'trace_sha256', 'wrong-trace'), ('bomb_rpc', 'rpc_sha256', 'wrong-rpc')):
        value = copy.deepcopy(positive); value['rows'][1]['bomb_instances'][field] = replacement
        negatives[name] = value
    value = copy.deepcopy(positive); value['bomb_instance_comparison_required'] = False
    negatives['bomb_not_required'] = value
'''
copy(OT / 'check-development-entry.py', T / 'check-development-entry.py', [
    ['    G.require_original_complete(positive, [11, 29], identity, helper_sha)\n', positive_addition],
    ["    checks['original_admission_negative_cases'] =", negative_addition + "    checks['original_admission_negative_cases'] ="],
    ['G.require_original_complete(v, [11, 29], identity, helper_sha)',
     'G.require_original_complete(v, [11, 29], identity, helper_sha, combiner_sha, checker_sha)'],
    ["    assert function(Path(O.__file__), 'one') == function(original_source, 'one')\n",
     "    expected_one = function(original_source, 'one')\n"
     "    for name in ('bomb_extras.py', 'bomb_instances.py'):\n"
     "        expected_one = expected_one.replace(f\"sha(ROOT / '{name}')\", f\"sha(G.ROOT / '{name}')\")\n"
     "    assert function(Path(O.__file__), 'one') == expected_one\n"],
    ["    checks['source_and_candidate_terminal_contract_identical'] = True\n",
     "    checks['source_and_candidate_terminal_contract_identical'] = True\n"
     "    assert function(C / 'run_collections.py', 'require_bomb_instances') == function(Path(G.__file__), 'require_bomb_instances')\n"
     "    collector.require_bomb_instances(positive, identity, combiner_sha, checker_sha)\n"
     "    for name, value in negatives.items():\n"
     "        if name.startswith('bomb_'):\n"
     "            rejected(lambda v=value: collector.require_bomb_instances(v, identity, combiner_sha, checker_sha))\n"
     "    checks['source_and_candidate_bomb_contract_identical'] = True\n"],
])

tp = json.loads(rebound((OT / 'protocol.json').read_text()))
tp.update(created_at=created, identity=identity, source_registration_sha256=sha(N / 'registration.json'),
    collector_registration_sha256=sha(C / 'registration.json'),
    inherited_training_registration_sha256=sha(OT / 'scale-training-registration.json'),
    implementation_change='Preserve the E114 fit, data, loader and choice recipe and family assignments. Renew bindings under E116. Require E117 per-instance Bomb comparisons alongside all existing twelve-stream terminal RNG and original-route checks.',
    dependency='All E117 source and original-development gates and E118 complete label audits. No model output directory before those gates pass.')
write(T / 'protocol.json', tp)
training_paths = [T / 'protocol.json', T / 'scale_training.py', N / 'registration.json',
    N / 'natural/manifest.json', N / 'family-groups.json', C / 'registration.json',
    R / 'runs/heart-independent-family-scale-20260920-01/protocol.json']
write(T / 'scale-training-registration.json', {'experiment': 'E119-training', 'created_at': created,
    'config': tp['config'], 'hashes': {str(p): sha(p) for p in training_paths}})
verification = json.loads(rebound((OT / 'scale-verification-registration.json').read_text()))
verification['created_at'] = created
verification['hashes'] = {p: sha(p) for p in verification['hashes']}
write(T / 'scale-verification-registration.json', verification)
dp = json.loads(rebound((OT / 'development-protocol.json').read_text()))
dp.update(created_at=created, identity=identity, parent_protocol_sha256=sha(T / 'protocol.json'),
    training_registration_sha256=sha(T / 'scale-training-registration.json'),
    verification_registration_sha256=sha(T / 'scale-verification-registration.json'),
    original_verification=dp['original_verification'] + ' Both live and recorded original execution compare every Bomb countdown and damage instance, including empty lists, using the frozen additive checker.',
    terminal_rng_helper_sha256=sha(T / 'terminal_rng.py'),
    bomb_combiner_sha256=sha(T / 'bomb_extras.py'),
    bomb_instance_checker_sha256=sha(T / 'bomb_instances.py'))
write(T / 'development-protocol.json', dp)
oldreg = read(OT / 'development-registration.json')
stale = {p: {'recorded_sha256': h, 'actual_sha256': sha(p)}
    for p, h in oldreg['original_harness_sha256'].items() if sha(p) != h}
reg = json.loads(rebound((OT / 'development-registration.json').read_text()))
reg['created_at'] = created
reg['original_harness_sha256'] = {p: sha(p) for p in reg['original_harness_sha256']}
for name in ('bomb_extras.py', 'bomb_instances.py'):
    reg['original_harness_sha256'][str(T / name)] = sha(T / name)
reg['hashes'] = {p: sha(p) for p in reg['hashes']}
reg['hashes'].update(reg['original_harness_sha256'])
write(T / 'development-registration.json', reg)
renewal = {'status': 'verified', 'driver_changes': changes,
    'frozen_collector_modules_byte_identical': 15, 'unchanged_scope_and_fit_recipe': True,
    'bomb_gate_addition': 'E117 one-route comparison and per-instance Bomb proof in source and candidate admission. The two candidate helper paths are resolved from G.ROOT.',
    'stale_inherited_nested_harness_hashes_rejected': stale,
    'source_registration_sha256': sha(N / 'registration.json'),
    'prior_data_entry_verification_sha256': read(OT / 'source-renewal-verification.json')['prior_data_entry_verification_sha256'],
    'inherited_preparation_sha256': sha(OT / 'preparation-publication-verification.json'),
    'new_mcts_calls': 0, 'optimizer_updates': 0}
write(T / 'source-renewal-verification.json', renewal)
# Publication is a separate final preparation step. Launcher controls run before
# publication, so bind execution to the immutable study inputs and own scripts.
execution = json.loads(rebound((OC / 'execution-registration.json').read_text()))
execution['created_at'] = created
execution['hashes'].pop('preparation-publication-verification.json')
execution['hashes'] = {p: sha(C / p) for p in execution['hashes']}
write(C / 'execution-registration.json', execution)
shutil.copyfile(__file__, T / 'preparation-source.py')
print({'prepared': [str(C), str(T)], 'drivers': len(changes),
       'stale_inherited_nested_hashes': len(stale), 'new_labels': 0, 'optimizer_updates': 0})
