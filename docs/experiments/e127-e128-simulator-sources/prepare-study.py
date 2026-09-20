"""Preserve E123/E124 and register the user-requested simulator-only study."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

R = Path(__file__).resolve().parents[1]
N = R / 'runs/heart-e121-scale-source-refresh-20260920-01'
OC = R / 'runs/heart-e121-scale-joint-labels-20260920-01'
OT = R / 'runs/heart-e121-scale-training-20260920-01'
C = R / 'runs/heart-e121-simulator-joint-labels-20260920-01'
T = R / 'runs/heart-e121-simulator-training-20260920-01'
AMENDMENT = N / 'user-scope-amendment.json'
created = datetime.now(timezone.utc).isoformat()
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def rebound(text):
    return text.replace(OC.name, C.name).replace(OT.name, T.name).replace('E123', 'E127').replace('E124', 'E128').replace('e123', 'e127').replace('e124', 'e128')


def functions(path):
    text = path.read_text()
    return {node.name: ast.get_source_segment(text, node) for node in ast.parse(text).body
            if isinstance(node, ast.FunctionDef)}


def reg(path, experiment, paths, **extra):
    write(path, {'experiment': experiment, 'created_at': created, **extra,
                 'hashes': {str(p): sha(p) for p in paths}})


assert read(AMENDMENT)['original_required_before_training'] is False
assert not C.exists() and not T.exists()
C.mkdir(); T.mkdir()
shutil.copytree(OC / 'frozen', C / 'frozen')
shutil.copyfile(OC / 'source-copy-verification.json', C / 'source-copy-verification.json')
for name in ('run_pipeline.py', 'check-launcher.py', 'check-entry.py'):
    (C / name).write_text(rebound((OC / name).read_text()))

# Drop native-only helpers and admission; retain complete simulator proofs.
text = rebound((OC / 'run_collections.py').read_text())
start = text.index('def require_terminal_rng(')
end = text.index('def source_ready(')
text = text[:start] + text[end:]
start = text.index('    source, parity = ')
end = text.index('    source_index = ', start)
text = text[:start] + '''    amendment = Path(plan['scope_amendment'])
    assert sha(amendment) == plan['scope_amendment_sha256']
    assert read(amendment)['original_required_before_training'] is False
    assert plan['evidence_scope'] == 'simulator_only'
    source = Path(plan['natural_source'])
    assert sha(source / 'manifest.json') == plan['source_manifest_sha256']
    for name, expected in read(source / 'manifest.json')['frozen_files'].items():
        assert sha(source / name) == expected, name
    roles = read(source / 'seeds.json')
    total = sum(plan['families'].values())
    assert {k: len(v) for k, v in roles.items()} == plan['families']
    assert len({s for values in roles.values() for s in values}) == total
    natural = proof(source)
    assert natural['zero_faults'] and natural['natural_terminals'] == total
    assert plan['identity'] == read(source / 'identity.json')
    report = read(source / 'report.json')
    assert report['status'] == 'complete' and report['identity'] == plan['identity']
    assert report['families'] == report['terminal_replays'] == total
    assert report['execution_faults'] == 0
    accounting = read(source / 'collection-accounting.json')
    assert accounting['requested'] == accounting['returned'] == total
    assert accounting['faults'] == []
''' + text[end:]
text = text.replace("             'parity_completion_sha256':sha(parity / 'completion-verification.json')}",
                    "             'scope_amendment_sha256': sha(amendment),\n             'evidence_scope': 'simulator_only', 'original_alignment_required': False}")
assert 'parity' not in text and 'require_turn_order' not in text
ast.parse(text)
(C / 'run_collections.py').write_text(text)
cp = read(OC / 'protocol.json')
for key in list(cp):
    if key.startswith(('parity_', 'terminal_rng_', 'bomb_', 'order_checker_')):
        del cp[key]
cp.update(experiment='E127', created_at=created, evidence_scope='simulator_only',
    scope_amendment=str(AMENDMENT), scope_amendment_sha256=sha(AMENDMENT),
    inherited_collector_registration_sha256=sha(OC / 'registration.json'),
    source_gates='All 6144 frozen E121 simulator sources, full terminal/state/RNG/timing/outside-NN audits and every winning replan. Missing, faulted or irreproducible simulator data blocks labels. Original-game comparisons are paused by user request.',
    limits='Simulator-only training under the user scope amendment. No original-game parity claim; old frozen evidence remains unchanged.')
cp['resources']['original_jvm_instances'] = 0
write(C / 'protocol.json', cp)
write(C / 'registration.json', {'experiment': 'E127', 'created_at': created,
    'hashes': {str(p.relative_to(C)): sha(p) for p in sorted(C.rglob('*'))
               if p.is_file() and (p.parent.name == 'frozen' or p.name in ('protocol.json', 'run_collections.py', 'source-copy-verification.json'))}})
ex = read(OC / 'execution-registration.json')
ex.update(experiment='E127-execution', created_at=created,
    gates='Complete simulator source evidence and exact-launcher software controls; no native game admission.',
    hashes={name: sha(C / name) for name in ex['hashes']})
write(C / 'execution-registration.json', ex)

# Fitting and heldout inference are unchanged except for experiment/path names.
for name in ('scale_training.py', 'scale_verify.py', 'check-training-execution.py'):
    (T / name).write_text(rebound((OT / name).read_text()))
tp = read(OT / 'protocol.json')
tp.update(experiment='E128', created_at=created, evidence_scope='simulator_only',
    scope_amendment_sha256=sha(AMENDMENT),
    collector_registration_sha256=sha(C / 'registration.json'),
    downstream='Heldout-qualified arms require all 512 natural simulator development games, net gain >=10 and paired p<.05, zero faults, full terminal/RNG/NN/timing audits, correct first-change scope and all winning replans. Select more wins, fewer lost parent wins, then small. No original-game prerequisite.',
    implementation_change='Keep both fit recipes and all family roles. Apply the user-requested simulator-only evidence boundary.',
    dependency='Complete E122 simulator sources and E127 complete audited joint labels. No original-game requirement or partial-data fit.')
write(T / 'protocol.json', tp)
for name, experiment in [('scale-training-registration.json', 'E128-training'), ('scale-verification-registration.json', 'E128-verification')]:
    old = read(OT / name)
    paths = [Path(rebound(p)) for p in old.pop('hashes')]
    old.pop('experiment'); old.pop('created_at')
    reg(T / name, experiment, paths, **old)

source = (OT / 'scale_development.py').read_text()
funcs = functions(OT / 'scale_development.py')
keep = ('registered', 'learning_ready', 'source_references', 'copy_runtime', 'audit_pairs',
        'natural', 'natural_ready', 'select_candidate', 'finalize')
text = rebound(source[:source.index('def registered')])
text = text.replace('original verification precedes selection', 'simulator-only evidence precedes selection')
for name in keep:
    body = rebound(funcs[name])
    if name == 'registered':
        body = body.replace("    for path, expected in reg['original_harness_sha256'].items():\n        assert sha(path) == expected, path\n", '')
    if name == 'finalize':
        start = body.index("        original = ROOT / 'original-candidates'")
        end = body.index('    selected = select_candidate', start)
        body = body[:start] + "        reports[arm]['original_gate_completed'] = False\n        reports[arm]['evidence_scope'] = 'simulator_only'\n" + body[end:]
        body = body.replace("'arms': reports, 'production_adoption': False", "'arms': reports, 'evidence_scope': 'simulator_only', 'original_alignment_required': False, 'production_adoption': False")
    text += body + '\n\n\n'
text += '''if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('check-gates', 'natural', 'finalize'))
    parser.add_argument('--arm', choices=ARMS)
    args = parser.parse_args()
    if args.command == 'check-gates': learning_ready()
    elif args.command == 'finalize': finalize()
    else:
        assert args.arm is not None
        natural(args.arm)
'''
ast.parse(text)
(T / 'scale_development.py').write_text(text)
dp = read(OT / 'development-protocol.json')
for key in list(dp):
    if key.startswith(('original_', 'terminal_rng_', 'bomb_', 'order_checker_', 'reference_game_')):
        del dp[key]
dp.update(experiment='E128D', created_at=created, evidence_scope='simulator_only',
    parent_protocol_sha256=sha(T / 'protocol.json'),
    training_registration_sha256=sha(T / 'scale-training-registration.json'),
    verification_registration_sha256=sha(T / 'scale-verification-registration.json'),
    purpose='Run the fixed natural-development screen and select using simulator outcomes.',
    prerequisites='All 6144 audited simulator sources, E127 joint labels, both E128 fits and complete heldout live-choice checks. Heldout gate unchanged.',
    candidate_selection='After complete natural screens: more Heart wins, fewer lost parent wins, then small. No native gate, automatic adoption or unseen draw.')
dp['resources'] = {k: v for k, v in dp['resources'].items() if 'original' not in k}
write(T / 'development-protocol.json', dp)
reg(T / 'development-registration.json', 'E128D-registration', [T / n for n in
    ('development-protocol.json', 'scale-training-registration.json', 'scale-verification-registration.json',
     'scale_training.py', 'scale_verify.py', 'scale_development.py')], evidence_scope='simulator_only')

# Reuse the tested process-group utility; no native launcher exists in this path.
text = rebound((OT / 'run_training_pipeline.py').read_text())
text = text.replace('with owned workers and native cleanup', 'with owned workers and simulator-only evidence')
start = text.index("    resolved = reg['resolved_stateless_bomb_helper']")
end = text.index('    for root in ', start)
text = text[:start] + text[end:]
start = text.index('def cleanup_originals():')
end = text.index('def emit_status(', start)
text = text[:start] + text[end:]
text = text.replace('    # All input and parity checks precede any formal outputs or child process.',
                    '    # Complete simulator source and label proofs precede formal outputs or children.')
text = text.replace("            T.NEW / 'label-verification.json',\n            Path(read(T.COLLECTOR / 'protocol.json')['parity_root']) / 'completion-verification.json')}",
                    "            T.NEW / 'label-verification.json')}")
start = text.index('            original = G.prepare_original(arm)')
end = text.index("        stage('finalize'", start)
text = text[:start] + "            transitions.append({'arm': arm, 'outcome': 'passed_simulator_natural_development',\n                                'natural_games_started': True, 'original_started': False})\n" + text[end:]
start = text.index('    finally:\n        try:\n            write(JOBS')
end = text.index("    result['execution_started_sha256']", start)
text = text[:start] + text[end:]
text = text.replace("'status': 'complete',\n            'jobs': jobs", "'status': 'complete', 'evidence_scope': 'simulator_only', 'original_alignment_required': False,\n            'jobs': jobs")
assert 'cleanup_originals' not in text and 'parity_root' not in text and 'prepare_original' not in text
ast.parse(text)
(T / 'run_training_pipeline.py').write_text(text)
write(T / 'preparation-diff.json', {'status': 'prepared', 'created_at': created,
    'user_scope_amendment_sha256': sha(AMENDMENT),
    'prior_registrations': {str(p): sha(p) for p in (OC / 'registration.json', OT / 'scale-training-registration.json')},
    'frozen_collector_modules_identical': {p.name: sha(p) for p in sorted((C / 'frozen').glob('*.py'))
        if sha(p) == sha(OC / 'frozen' / p.name)},
    'fit_and_live_choice_rebind_only': {n: sha(T / n) for n in ('scale_training.py', 'scale_verify.py')
        if (T / n).read_text() == rebound((OT / n).read_text())},
    'original_admission_removed': True, 'engine_changed': False, 'new_labels': 0, 'optimizer_updates': 0})
print({'collector': str(C), 'training': str(T), 'scope': 'simulator_only'})
