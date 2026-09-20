"""Renew the unexecuted scale study with E121 turn-order admission."""
from pathlib import Path
from datetime import datetime, timezone
import ast
import hashlib
import json
import shutil

R = Path(__file__).resolve().parents[1]
A = R.parent / 'ironclad-alignment'
OC = R / 'runs/heart-e116-scale-joint-labels-20260920-01'
OT = R / 'runs/heart-e116-scale-training-20260920-01'
C = R / 'runs/heart-e121-scale-joint-labels-20260920-01'
T = R / 'runs/heart-e121-scale-training-20260920-01'
N = R / 'runs/heart-e121-scale-source-refresh-20260920-01'
Q = A / 'evidence/e122-development-parity-20260920-01'
S = A / 'evidence/e121-power-order-repair-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
created = datetime.now(timezone.utc).isoformat()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


common = [
    ['heart-e116-scale-source-refresh-20260920-01', N.name],
    [OC.name, C.name], [OT.name, T.name],
    ['e117-development-parity-20260920-01', Q.name],
    ['e116-bomb-instance-repair-20260920-01', S.name],
    ['E119', 'E124'], ['E118', 'E123'], ['E117', 'E122'], ['E116', 'E121'],
    ['e119', 'e124'], ['e118', 'e123'], ['e117', 'e122'],
    ['bomb_extras.py', 'turn_extras.py'], ['import bomb_extras', 'import turn_extras'],
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


turn_contract = '''
def require_turn_order(proof, identity, combiner_sha, checker_sha):
    assert proof['turn_order_comparison_required'] is True
    for row in proof['rows']:
        order = row['turn_order']
        assert order['status'] == 'matched' and order['seed'] == row['seed']
        assert order['engine_sha256'] == identity['engine_sha256']
        assert order['combiner_sha256'] == combiner_sha
        assert order['order_checker_sha256'] == checker_sha
        assert order['phases'] == ['end', 'start', 'post_draw']
        for phase in ('live', 'recorded'):
            checks, bearing = order[phase + '_checks'], order[phase + '_order_bearing_checks']
            assert type(checks) is int and checks > 0
            assert type(bearing) is int and 0 <= bearing <= checks
        assert order['state_imports'] == 0 and order['resynchronized'] is False
        assert order['trace_sha256'] == proof['hashes'][f"traces/{row['seed']}.json"]
        assert order['rpc_sha256'] == proof['hashes'][f"original/{row['seed']}-01/rpc.jsonl.gz"]

'''


assert not C.exists() and not T.exists()
assert read(S / 'completion-verification.json')['status'] == 'complete'
assert (OC / 'source-closed.json').exists() and (OT / 'source-closed.json').exists()
identity = read(N / 'natural/identity.json')
assert identity['engine_sha256'] == read(S / 'completion-verification.json')['engine_sha256']
for root in (C, T):
    root.mkdir()
shutil.copytree(OC / 'frozen', C / 'frozen', ignore=shutil.ignore_patterns('__pycache__'))
shutil.copyfile(OC / 'source-copy-verification.json', C / 'source-copy-verification.json')
assert len(list((C / 'frozen').glob('*.py'))) == 15
assert all(sha(p) == sha(OC / 'frozen' / p.name) for p in (C / 'frozen').glob('*.py'))
copy(OC / 'run_collections.py', C / 'run_collections.py', [
    ['def source_ready(root):', turn_contract + '\ndef source_ready(root):'],
    ["    require_bomb_instances(original, plan['identity'], plan['bomb_combiner_sha256'], plan['bomb_instance_checker_sha256'])\n",
     "    require_bomb_instances(original, plan['identity'], plan['bomb_combiner_sha256'], plan['bomb_instance_checker_sha256'])\n"
     "    assert sha(parity / 'power_order.py') == plan['order_checker_sha256']\n"
     "    require_turn_order(original, plan['identity'], plan['bomb_combiner_sha256'], plan['order_checker_sha256'])\n"],
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
    bomb_combiner_sha256=sha(Q / 'turn_extras.py'),
    bomb_instance_checker_sha256=sha(Q / 'bomb_instances.py'),
    order_checker_sha256=sha(Q / 'power_order.py'),
    source_gates=cp['source_gates'] + ' Each original route also needs ordered end, start and post-draw power comparison in live and recorded execution, linked to the same trace and RPC.',
    limits='Label preparation under E121 until all E122 gates pass. E117/E118/E119 stay stopped or closed; no old-engine outcomes admitted. The scale hypothesis remains untested; no learned gain or unseen acceptance.')
write(C / 'protocol.json', cp)
write(C / 'registration.json', {'experiment': 'E123', 'created_at': created,
    'hashes': {str(p.relative_to(C)): sha(p) for p in sorted(C.rglob('*'))
        if p.is_file() and p.name not in ('check-entry.py', 'run_pipeline.py', 'check-launcher.py')}})

for name in ('scale_training.py', 'scale_verify.py', 'run-native-probe.py',
             'check-renewal-entry.py', 'prepare-native-probe.py', 'terminal_rng.py'):
    copy(OT / name, T / name)
for name in ('turn_extras.py', 'bomb_instances.py', 'power_order.py'):
    copy(Q / name, T / name, bindings=False)
copy(OT / 'scale_development.py', T / 'scale_development.py', [
    ['def require_original_complete(proof, expected, identity, terminal_helper_sha, bomb_combiner_sha, bomb_checker_sha):',
     turn_contract + '\ndef require_original_complete(proof, expected, identity, terminal_helper_sha, bomb_combiner_sha, bomb_checker_sha, order_checker_sha):'],
    ['    require_bomb_instances(proof, identity, bomb_combiner_sha, bomb_checker_sha)\n',
     '    require_bomb_instances(proof, identity, bomb_combiner_sha, bomb_checker_sha)\n'
     '    require_turn_order(proof, identity, bomb_combiner_sha, order_checker_sha)\n'],
    ["                                  sha(ROOT / 'turn_extras.py'), sha(ROOT / 'bomb_instances.py'))\n",
     "                                  sha(ROOT / 'turn_extras.py'), sha(ROOT / 'bomb_instances.py'),\n"
     "                                  sha(ROOT / 'power_order.py'))\n"],
])
one = function(Q / 'cohort.py', 'one')
for name in ('turn_extras.py', 'bomb_instances.py', 'power_order.py'):
    one = one.replace(f"sha(ROOT / '{name}')", f"sha(G.ROOT / '{name}')")
copy(OT / 'candidate_original.py', T / 'candidate_original.py', [
    [rebound(function(OT / 'candidate_original.py', 'one')), one],
    ['                verified.append(checked)',
     '                order = read(ROOT / f"power-order/{result[\'seed\']}.json")\n'
     "                assert order == result['turn_order']\n"
     "                G.require_turn_order({'turn_order_comparison_required': True, 'rows': [result],\n"
     "                    'hashes': {f\"traces/{result['seed']}.json\": sha(ROOT / f\"traces/{result['seed']}.json\"),\n"
     "                        f\"original/{result['seed']}-01/rpc.jsonl.gz\": sha(ROOT / f\"original/{result['seed']}-01/rpc.jsonl.gz\")}},\n"
     "                    reg['identity'], sha(G.ROOT / 'turn_extras.py'), sha(G.ROOT / 'power_order.py'))\n"
     '                verified.append(checked)'],
    ["'terminal_rng_streams_per_route': 12, 'bomb_instance_comparison_required': True,",
     "'terminal_rng_streams_per_route': 12, 'bomb_instance_comparison_required': True,\n"
     "            'turn_order_comparison_required': True,"],
])

positive_addition = '''    order_checker_sha = 'fixture-order-checker'
    positive['turn_order_comparison_required'] = True
    for row in positive['rows']:
        row['turn_order'] = {
            'status': 'matched', 'seed': row['seed'], 'engine_sha256': identity['engine_sha256'],
            'combiner_sha256': combiner_sha, 'order_checker_sha256': order_checker_sha,
            'phases': ['end', 'start', 'post_draw'],
            'live_checks': 7, 'recorded_checks': 7,
            'live_order_bearing_checks': 3, 'recorded_order_bearing_checks': 3,
            'trace_sha256': row['terminal_rng']['trace_sha256'], 'rpc_sha256': row['terminal_rng']['rpc_sha256'],
            'state_imports': 0, 'resynchronized': False}
    G.require_original_complete(positive, [11, 29], identity, helper_sha, combiner_sha, checker_sha, order_checker_sha)
'''
negative_addition = '''    for name, field, replacement in (
        ('order_status', 'status', 'mismatch'), ('order_seed', 'seed', 30),
        ('order_engine', 'engine_sha256', 'wrong-engine'),
        ('order_combiner', 'combiner_sha256', 'old-combiner'),
        ('order_checker', 'order_checker_sha256', 'old-checker'),
        ('order_phase_missing', 'phases', ['end', 'start']),
        ('order_phase_changed', 'phases', ['start', 'end', 'post_draw']),
        ('order_no_live_checks', 'live_checks', 0), ('order_no_recorded_checks', 'recorded_checks', 0),
        ('order_live_bool', 'live_checks', True), ('order_recorded_float', 'recorded_checks', 7.0),
        ('order_negative_live', 'live_order_bearing_checks', -1),
        ('order_negative_recorded', 'recorded_order_bearing_checks', -1),
        ('order_impossible_live', 'live_order_bearing_checks', 8),
        ('order_impossible_recorded', 'recorded_order_bearing_checks', 8),
        ('order_bearing_bool', 'live_order_bearing_checks', True),
        ('order_bearing_float', 'recorded_order_bearing_checks', 3.0),
        ('order_import', 'state_imports', 1), ('order_resync', 'resynchronized', True),
        ('order_trace', 'trace_sha256', 'wrong-trace'), ('order_rpc', 'rpc_sha256', 'wrong-rpc')):
        value = copy.deepcopy(positive); value['rows'][1]['turn_order'][field] = replacement
        negatives[name] = value
    value = copy.deepcopy(positive); value['turn_order_comparison_required'] = False
    negatives['order_not_required'] = value
    for field in ('turn_order',):
        value = copy.deepcopy(positive); del value['rows'][1][field]
        checks['missing_' + field + '_rejected'] = rejected(lambda v=value:
            G.require_original_complete(v, [11, 29], identity, helper_sha, combiner_sha, checker_sha, order_checker_sha), KeyError)
    value = copy.deepcopy(positive); del value['turn_order_comparison_required']
    checks['missing_order_requirement_rejected'] = rejected(lambda:
        G.require_original_complete(value, [11, 29], identity, helper_sha, combiner_sha, checker_sha, order_checker_sha), KeyError)
'''
copy(OT / 'check-development-entry.py', T / 'check-development-entry.py', [
    ['    G.require_original_complete(positive, [11, 29], identity, helper_sha, combiner_sha, checker_sha)\n', positive_addition],
    ["    checks['original_admission_negative_cases'] =", negative_addition + "    checks['original_admission_negative_cases'] ="],
    ['G.require_original_complete(v, [11, 29], identity, helper_sha, combiner_sha, checker_sha)',
     'G.require_original_complete(v, [11, 29], identity, helper_sha, combiner_sha, checker_sha, order_checker_sha)'],
    ["    for name in ('turn_extras.py', 'bomb_instances.py'):\n",
     "    for name in ('turn_extras.py', 'bomb_instances.py', 'power_order.py'):\n"],
    ["    checks['source_and_candidate_bomb_contract_identical'] = True\n",
     "    checks['source_and_candidate_bomb_contract_identical'] = True\n"
     "    assert function(C / 'run_collections.py', 'require_turn_order') == function(Path(G.__file__), 'require_turn_order')\n"
     "    collector.require_turn_order(positive, identity, combiner_sha, order_checker_sha)\n"
     "    for name, value in negatives.items():\n"
     "        if name.startswith('order_'):\n"
     "            rejected(lambda v=value: collector.require_turn_order(v, identity, combiner_sha, order_checker_sha))\n"
     "    checks['source_and_candidate_turn_contract_identical'] = True\n"],
])

tp = json.loads(rebound((OT / 'protocol.json').read_text()))
tp.update(created_at=created, identity=identity, source_registration_sha256=sha(N / 'registration.json'),
    collector_registration_sha256=sha(C / 'registration.json'),
    inherited_training_registration_sha256=sha(OT / 'scale-training-registration.json'),
    implementation_change='Preserve the E119 fit, data, loader and choice recipe and family assignments. Renew bindings under E121. Require E122 turn-phase order alongside per-instance Bomb, twelve-stream terminal RNG and original-route checks.',
    dependency='All E122 source and original-development gates and E123 complete label audits. No model output directory before those gates pass.')
write(T / 'protocol.json', tp)
training_paths = [T / 'protocol.json', T / 'scale_training.py', N / 'registration.json',
    N / 'natural/manifest.json', N / 'family-groups.json', C / 'registration.json',
    R / 'runs/heart-independent-family-scale-20260920-01/protocol.json']
write(T / 'scale-training-registration.json', {'experiment': 'E124-training', 'created_at': created,
    'config': tp['config'], 'hashes': {str(p): sha(p) for p in training_paths}})
verification = json.loads(rebound((OT / 'scale-verification-registration.json').read_text()))
verification['created_at'] = created
verification['hashes'] = {p: sha(p) for p in verification['hashes']}
write(T / 'scale-verification-registration.json', verification)
dp = json.loads(rebound((OT / 'development-protocol.json').read_text()))
dp.update(created_at=created, identity=identity, parent_protocol_sha256=sha(T / 'protocol.json'),
    training_registration_sha256=sha(T / 'scale-training-registration.json'),
    verification_registration_sha256=sha(T / 'scale-verification-registration.json'),
    original_verification=dp['original_verification'] + ' Both executions also compare ordered end, start and post-draw player powers, with a per-route proof bound to the same trace and RPC.',
    terminal_rng_helper_sha256=sha(T / 'terminal_rng.py'),
    bomb_combiner_sha256=sha(T / 'turn_extras.py'),
    bomb_instance_checker_sha256=sha(T / 'bomb_instances.py'),
    order_checker_sha256=sha(T / 'power_order.py'))
write(T / 'development-protocol.json', dp)
oldreg = read(OT / 'development-registration.json')
stale = {p: {'recorded_sha256': h, 'actual_sha256': sha(p)}
    for p, h in oldreg['original_harness_sha256'].items() if sha(p) != h}
assert not stale, 'do not silently inherit mutated prior harness'
reg = json.loads(rebound((OT / 'development-registration.json').read_text()))
reg['created_at'] = created
reg['original_harness_sha256'] = {p: sha(p) for p in reg['original_harness_sha256']}
reg['original_harness_sha256'][str(T / 'power_order.py')] = sha(T / 'power_order.py')
reg['hashes'] = {p: sha(p) for p in reg['hashes']}
reg['hashes'].update(reg['original_harness_sha256'])
write(T / 'development-registration.json', reg)
write(T / 'source-renewal-verification.json', {'status': 'verified', 'driver_changes': changes,
    'frozen_collector_modules_byte_identical': 15, 'unchanged_scope_and_fit_recipe': True,
    'turn_gate_addition': 'E122 one-route comparison plus ordered player powers in end, start and post-draw phases for both source and candidate admission. All three helpers resolve from G.ROOT.',
    'stale_inherited_nested_harness_hashes_rejected': stale,
    'source_registration_sha256': sha(N / 'registration.json'),
    'prior_data_entry_verification_sha256': read(OT / 'source-renewal-verification.json')['prior_data_entry_verification_sha256'],
    'inherited_preparation_sha256': sha(OT / 'preparation-publication-verification.json'),
    'new_mcts_calls': 0, 'optimizer_updates': 0})
execution = json.loads(rebound((OC / 'execution-registration.json').read_text()))
execution['created_at'] = created
execution['hashes'] = {p: sha(C / p) for p in execution['hashes']}
write(C / 'execution-registration.json', execution)
shutil.copyfile(__file__, T / 'preparation-source.py')
print({'prepared': [str(C), str(T)], 'drivers': len(changes),
       'new_labels': 0, 'optimizer_updates': 0})
