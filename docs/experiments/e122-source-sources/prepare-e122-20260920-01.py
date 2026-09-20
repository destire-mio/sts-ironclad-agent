"""Renew the unchanged scale-source study after the E121 completion gate."""
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
OLD = R / 'runs/heart-e116-scale-source-refresh-20260920-01'
OLD_Q = A / 'evidence/e117-development-parity-20260920-01'
REPAIR = A / 'evidence/e121-power-order-repair-20260920-01'
N = R / 'runs/heart-e121-scale-source-refresh-20260920-01'
Q = A / 'evidence/e122-development-parity-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')
def rebound(text):
    for old, new in [(str(OLD), str(N)), (OLD.name, N.name), (str(OLD_Q), str(Q)),
            (OLD_Q.name, Q.name), ('E117', 'E122'), ('e117', 'e122'),
            ('e116-bomb-instance-repair', 'e121-power-order-repair'), ('E116', 'E121')]:
        text = text.replace(old, new)
    return text
def script(source, target, changes=()):
    text = rebound(source.read_text())
    for before, after in changes:
        assert text.count(before) == 1, (source, before)
        text = text.replace(before, after)
    ast.parse(text)
    with target.open('x') as f: f.write(text)

turn_contract = '''
def require_turn_order(proof, seed, identity, trace_sha, rpc_sha):
    assert proof['status'] == 'matched' and proof['seed'] == seed
    assert proof['engine_sha256'] == identity['engine_sha256']
    assert proof['combiner_sha256'] == sha(ROOT / 'turn_extras.py')
    assert proof['order_checker_sha256'] == sha(ROOT / 'power_order.py')
    assert proof['phases'] == ['end', 'start', 'post_draw']
    for phase in ('live', 'recorded'):
        checks, bearing = proof[phase + '_checks'], proof[phase + '_order_bearing_checks']
        assert type(checks) is int and checks > 0
        assert type(bearing) is int and 0 <= bearing <= checks
    assert proof['state_imports'] == 0 and proof['resynchronized'] is False
    assert proof['trace_sha256'] == trace_sha and proof['rpc_sha256'] == rpc_sha

'''

# Never create a successor or admit old outcomes before E121 is complete.
proof = read(REPAIR / 'completion-verification.json')
assert proof['status'] == 'complete' and proof['source_refresh_permitted']
for name, expected in proof['hashes'].items(): assert sha(REPAIR / name) == expected, name
assert read(OLD / 'stop-verification.json')['status'] == 'stopped_on_external_confirmed_rule_difference'
assert not N.exists() and not Q.exists()
N.mkdir(); Q.mkdir()
protocol = copy.deepcopy(read(OLD / 'protocol.json'))
protocol.update(experiment='E122', created_at=datetime.now(timezone.utc).isoformat(),
    question='Regenerate the unchanged 6144 families under E121 before joint relic/card scale training. Player turn order is repaired; the data-scale hypothesis remains untested.',
    source_runtime=str(REPAIR / 'candidate'), source_manifest_sha256=sha(REPAIR / 'candidate/manifest.json'),
    repair_completion=str(REPAIR / 'completion-verification.json'),
    repair_completion_sha256=sha(REPAIR / 'completion-verification.json'),
    repair_publication_sha256=sha(REPAIR / 'publication-verification.json'),
    previous_source_stop_sha256=sha(OLD / 'stop-verification.json'),
    limits='Known-family source renewal after E121, not a learned gain or unseen acceptance. E117 stopped; E118/E119 closed. Every new source outcome and downstream label must use E121.')
protocol['scope']['engine_sha256'] = proof['engine_sha256']
protocol['gates'] = [rebound(value) for value in protocol['gates']]
protocol['gates'][1] += ' Native and recorded routes must also match player order in all three repaired turn phases, with positive comparison counts and source/RPC/helper hashes.'
write(N / 'protocol.json', protocol)
script(OLD / 'prepare_source.py', N / 'prepare_source.py')
write(N / 'registration.json', {'hashes': {name: sha(N / name) for name in ('protocol.json', 'prepare_source.py')}})
subprocess.run([sys.executable, N / 'prepare_source.py'], check=True)
assert sha(N / 'seeds.json') == sha(OLD / 'seeds.json')
assert sha(N / 'family-groups.json') == sha(OLD / 'family-groups.json')

turn_proof = '''        order_proof = {'status': instance_proof['status'], 'seed': seed,
            'engine_sha256': reg['identity']['engine_sha256'],
            'combiner_sha256': sha(ROOT / 'turn_extras.py'), 'order_checker_sha256': sha(ROOT / 'power_order.py'),
            'phases': ['end', 'start', 'post_draw'],
            'live_checks': live_checks, 'recorded_checks': B.checks - live_checks,
            'live_order_bearing_checks': live_order, 'recorded_order_bearing_checks': B.order_bearing_checks - live_order,
            'trace_sha256': sha(trace), 'rpc_sha256': sha(native / 'rpc.jsonl.gz'),
            'state_imports': 0, 'resynchronized': False}
        write(ROOT / f'power-order/{seed}.json', order_proof)
        result['turn_order'] = order_proof
'''
verified = '''                order_proof = read(ROOT / f"power-order/{result['seed']}.json")
                assert order_proof == result['turn_order']
                require_turn_order(order_proof, result['seed'], reg['identity'],
                    sha(ROOT / f"traces/{result['seed']}.json"), sha(ROOT / f"original/{result['seed']}-01/rpc.jsonl.gz"))
'''
text = rebound((OLD_Q / 'cohort.py').read_text())
text = text.replace('import bomb_extras as B', 'import turn_extras as B')
text = text.replace("ROOT / 'bomb_extras.py'", "ROOT / 'turn_extras.py'")
changes = [
    ('def one(seed):', turn_contract + '\ndef one(seed):'),
    ('    live_checks, live_bearing = B.checks, B.bomb_bearing_checks',
     '    live_checks, live_bearing = B.checks, B.bomb_bearing_checks\n    live_order = B.order_bearing_checks'),
    ("        result['bomb_instances'] = instance_proof", "        result['bomb_instances'] = instance_proof\n" + turn_proof.rstrip()),
    ('                verified.append(checked)', verified + '                verified.append(checked)'),
    ("'bomb_instance_comparison_required': True,", "'bomb_instance_comparison_required': True, 'turn_order_comparison_required': True,")]
for before, after in changes:
    assert text.count(before) == 1, before
    text = text.replace(before, after)
ast.parse(text)
with (Q / 'cohort.py').open('x') as f: f.write(text)
for name in ('bomb_instances.py', 'turn_extras.py', 'power_order.py'):
    shutil.copyfile(REPAIR / name, Q / name)
shutil.copyfile(OLD_Q / 'terminal_rng.py', Q / 'terminal_rng.py')
reg = copy.deepcopy(read(OLD_Q / 'registration.json'))
reg.update(experiment='E122P', created_at=datetime.now(timezone.utc).isoformat(), source=str(N / 'natural'),
    source_manifest_sha256=sha(N / 'natural/manifest.json'), source_roles_sha256=sha(N / 'natural/seeds.json'),
    parent_registration_sha256=sha(N / 'registration.json'), identity=read(N / 'natural/identity.json'),
    reuse_source_cohort_sha256=sha(OLD_Q / 'cohort.py'))
reg['selection'] = rebound(reg['selection'])
reg['verification'] = rebound(reg['verification']) + ' Add phase-specific player power order to live and recorded checks.'
reg['limits'] = 'All 512 assigned development families audited; every development winner replayed. No original winning route may lack turn-order, Bomb-instance or twelve-stream terminal RNG evidence. Not unseen acceptance.'
reg['changes_from_E117'] = 'Renew engine source and add the three repaired turn phases to the existing Bomb and RNG gate. Budgets, seed roles and base model unchanged.'
reg.pop('changes_from_E112', None)
reg['harness_sha256'] = {rebound(name): sha(Path(rebound(name)))
    for name in reg['harness_sha256'] if Path(name).name != 'bomb_extras.py'}
for name in ('bomb_instances.py', 'turn_extras.py', 'power_order.py'):
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
    'limits': 'Execution wrapper and comparison-gate entry checks are required before launch.'})
print({'prepared': str(N), 'original_gate': str(Q), 'not_launched': True})
