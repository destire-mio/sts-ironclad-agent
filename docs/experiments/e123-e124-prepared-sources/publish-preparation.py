"""Publish E123/E124 preparation, with no live source outcomes or private data."""
from pathlib import Path
from datetime import datetime, timezone
import ast
import hashlib
import json
import shutil
import scale_training as ST
import scale_development as G

T = ST.ROOT
C, N = ST.COLLECTOR, ST.SOURCE
R = T.parents[1]
D = R / 'docs/experiments'
PUBLIC = D / 'e123-e124-prepared-sources'
sha, read, write = ST.sha, ST.read, ST.write
created = datetime.now(timezone.utc).isoformat()


def hashes(root, proof):
    for name, digest in proof.get('hashes', {}).items():
        assert sha(root / name) == digest, name


assert not PUBLIC.exists() and not ST.OUTPUT.exists()
assert not (C / 'relic-source').exists() and not (C / 'joint').exists()
assert not (T / 'original-candidates').exists()
ST.check_registration()
G.registered()
hashes(C, read(C / 'registration.json'))
hashes(C, read(C / 'execution-registration.json'))
entry = read(C / 'entry-verification.json')
assert entry['status'] == 'complete' and entry['incomplete_natural_source_rejected']
assert entry['registration_sha256'] == sha(C / 'registration.json')
assert entry['checker_sha256'] == sha(C / 'check-entry.py')
launcher = read(C / 'launcher-probe/completion-verification.json')
hashes(C / 'launcher-probe', launcher)
assert launcher['status'] == 'passed' and len(launcher['cases']) == 4
assert launcher['launcher_sha256'] == sha(C / 'run_pipeline.py')
assert launcher['checker_sha256'] == sha(C / 'check-launcher.py')
assert launcher['collector_registration_sha256'] == sha(C / 'registration.json')
assert all(x['cleanup'] and x['unrelated_job_alive'] for x in launcher['cases'])
renewal = read(T / 'source-renewal-verification.json')
for dest, item in renewal['driver_changes'].items():
    assert sha(item['source']) == item['before_sha256']
    text = Path(item['source']).read_text()
    for before, after in item['allowed_replacements']:
        text = text.replace(before, after)
    assert Path(dest).read_text() == text and sha(dest) == item['after_sha256']
assert renewal['frozen_collector_modules_byte_identical'] == 15
renewal_entry = read(T / 'renewal-entry-verification.json')
assert renewal_entry['status'] == 'passed' and renewal_entry['driver_rebindings_checked'] == 16
assert renewal_entry['renewal_proof_sha256'] == sha(T / 'source-renewal-verification.json')
assert renewal_entry['checker_sha256'] == sha(T / 'check-renewal-entry.py')
native = read(T / 'native-probe/completion-verification.json')
hashes(T / 'native-probe', native)
assert native['status'] == 'passed'
assert [c['status'] for c in native['cases']] == ['verified', 'verification_error', 'verification_error']
development = read(T / 'development-entry-probe/completion-verification.json')
hashes(T / 'development-entry-probe', development)
assert development['status'] == 'passed'
assert development['registration_sha256'] == sha(T / 'development-registration.json')
checks = development['checks']
assert len(checks['original_admission_negative_cases']) == 54
assert all(v['rejected'] for v in checks['original_admission_negative_cases'].values())
assert checks['missing_turn_order_rejected']['rejected'] and checks['missing_order_requirement_rejected']['rejected']
assert checks['zero_head_whole_route']['outside_choices'] == 203
assert all(checks[f'source_and_candidate_{name}_contract_identical'] for name in ('terminal', 'bomb', 'turn'))
admission = read(T / 'native-admission-verification.json')
assert admission['status'] == 'passed' and len(admission['nested_harness_negatives']) == 8
assert admission['registration_sha256'] == sha(T / 'development-registration.json')
assert admission['checker_sha256'] == sha(T / 'check-native-admission.py')
terminal = admission['saved_native_admission']['rows'][0]['terminal_rng']
assert terminal['natural_actions'] == 965
assert admission['native_bomb_control_states'] == 15 and admission['native_order_control_states'] == 11
assert sha(admission['resolved_bomb_helper']['path']) == admission['resolved_bomb_helper']['sha256']
identity = read(T / 'protocol.json')['identity']
assert entry['runtime_identity'] == identity
assert native['engine_sha256'] == development['engine_sha256'] == terminal['engine_sha256'] == identity['engine_sha256']
G.require_original_complete(admission['saved_native_admission'], [terminal['seed']], identity,
    sha(T / 'terminal_rng.py'), sha(T / 'turn_extras.py'), sha(T / 'bomb_instances.py'), sha(T / 'power_order.py'))
for item in (renewal_entry, development, admission):
    assert item['new_mcts_calls'] == item['optimizer_updates'] == 0
assert sha(R / 'runs/prepare-e123-e124-20260920-01.py') == sha(T / 'preparation-source.py')

PUBLIC.mkdir()
sources = {'prepare-e123-e124.py': T / 'preparation-source.py', 'publish-preparation.py': Path(__file__)}
for root, names, prefix in (
    (C, ('run_collections.py', 'check-entry.py', 'run_pipeline.py', 'check-launcher.py'), 'collector'),
    (T, ('scale_training.py', 'scale_verify.py', 'scale_development.py', 'candidate_original.py',
        'terminal_rng.py', 'turn_extras.py', 'bomb_instances.py', 'power_order.py',
        'check-renewal-entry.py', 'prepare-native-probe.py', 'run-native-probe.py',
        'check-development-entry.py', 'check-native-admission.py'), 'training')):
    for name in names:
        sources[prefix + '/' + name] = root / name
for name, source in sources.items():
    ast.parse(source.read_text())
    dest = PUBLIC / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    assert sha(source) == sha(dest)
(PUBLIC / 'README.md').write_text(
    'Own-code E123/E124 preparation snapshots under the E121 engine. These depend on the local '
    'frozen evidence layout and earlier collector modules; they are not standalone runners. '
    'No game JARs, weights or raw traces are included.\n\n'
    'The unchanged study compares 1536 versus 4608 fit families, with 1024 common heldout and 512 '
    'development families. Source, all original development winners and complete continuation audits '
    'precede fitting. Live and recorded originals need per-instance Bomb, ordered end/start/post-draw '
    'powers and twelve terminal RNG streams. Preparation creates no labels or optimizer updates.\n')
collection = {'experiment': 'E123', 'status': 'preparation_complete', 'created_at': created,
    'protocol': read(C / 'protocol.json'), 'registration_sha256': sha(C / 'registration.json'),
    'entry_sha256': sha(C / 'entry-verification.json'),
    'execution_registration_sha256': sha(C / 'execution-registration.json'),
    'launcher_controls_sha256': sha(C / 'launcher-probe/completion-verification.json'),
    'launcher_cases': [x['case'] for x in launcher['cases']],
    'frozen_collector_modules_byte_identical': 15,
    'entry_known_source': entry['known_E121_source_replay'],
    'new_continuation_labels': 0, 'optimizer_updates': 0, 'collection_started': False,
    'limits': 'Prepared collection only. Full E122 source, winner replans and every development-winning original route must pass before labels.'}
training = {'experiment': 'E124', 'status': 'preparation_complete', 'created_at': created,
    'protocol': read(T / 'protocol.json'), 'development_protocol': read(T / 'development-protocol.json'),
    'registrations': {name: sha(T / name) for name in ('scale-training-registration.json',
        'scale-verification-registration.json', 'development-registration.json')},
    'proofs': {name: sha(T / name) for name in ('source-renewal-verification.json',
        'renewal-entry-verification.json', 'native-probe/completion-verification.json',
        'development-entry-probe/completion-verification.json', 'native-admission-verification.json')},
    'driver_rebindings_checked': 16, 'same_collector_modules': 15,
    'explicit_nested_hash_rejection_controls': 8, 'native_choice_cases': native['cases'],
    'outside_NN_choices_checked': 203, 'candidate_selection_cases': checks['selection_order_cases'],
    'original_admission_rejection_cases': list(checks['original_admission_negative_cases']),
    'missing_turn_order_rejected': True, 'missing_order_requirement_rejected': True,
    'source_and_candidate_turn_contract_identical': True,
    'terminal_rng_streams_checked': len(terminal['rng_streams']), 'saved_natural_actions': 965,
    'native_bomb_control_states': 15, 'native_order_control_states': 11,
    'same_total_wrong_instances_rejected': True, 'wrong_countdown_rejected': True,
    'same_amount_wrong_turn_order_rejected': True,
    'saved_natural_route_bomb_bearing_checks': 0,
    'saved_natural_route_order_bearing_checks': admission['saved_native_admission']['rows'][0]['turn_order']['live_order_bearing_checks'],
    'new_continuation_labels': 0, 'optimizer_updates': 0, 'new_mcts_calls': 0,
    'new_original_executions': 0, 'unseen_acceptance_games': 0,
    'limits': 'Software preparation and saved native evidence on a known route with zero-head fixtures. No trained model, new candidate-original cohort or population win-rate evidence.'}
write(D / 'e123-label-preparation.json', collection)
write(D / 'e124-training-preparation.json', training)
public_hashes = {str(p.relative_to(R)): sha(p) for p in PUBLIC.rglob('*') if p.is_file()}
public_hashes.update({str(p.relative_to(R)): sha(p) for p in (D / 'e123-label-preparation.json', D / 'e124-training-preparation.json')})
publication = {'status': 'verified', 'created_at': created, 'identity': identity,
    'collector_registration_sha256': sha(C / 'registration.json'),
    'training_registration_sha256': sha(T / 'scale-training-registration.json'),
    'source_registration_sha256': sha(N / 'registration.json'),
    'public_hashes': public_hashes, 'raw_private_artifacts_published': False,
    'live_source_outcomes_read': False, 'formal_optimizer_updates': 0}
write(C / 'preparation-publication-verification.json', publication)
write(T / 'preparation-publication-verification.json', publication)
print({'status': 'verified', 'public_files': len(public_hashes), 'optimizer_updates': 0})
