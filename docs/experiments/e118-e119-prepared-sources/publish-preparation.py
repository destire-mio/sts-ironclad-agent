"""Publish own-code preparation and verified controls; never read live outcomes."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil

T = Path(__file__).resolve().parent
R = T.parents[1]
W = R.parent
C = T.parent / 'heart-e116-scale-joint-labels-20260920-01'
N = T.parent / 'heart-e116-scale-source-refresh-20260920-01'
D = R / 'docs/experiments'
PUBLIC = D / 'e118-e119-prepared-sources'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
created = datetime.now(timezone.utc).isoformat()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def check_hashes(root, proof):
    for path, expected in proof.get('hashes', {}).items():
        assert sha(root / path) == expected, path


assert not PUBLIC.exists()
assert not (C / 'relic-source').exists() and not (C / 'joint').exists()
assert not (T / 'trained').exists() and not (T / 'original-candidates').exists()
import scale_training as ST
assert not ST.OUTPUT.exists()
registration = read(C / 'registration.json')
check_hashes(C, registration)
check_hashes(C, read(C / 'execution-registration.json'))
entry = read(C / 'entry-verification.json')
assert entry['status'] == 'complete' and entry['incomplete_natural_source_rejected']
assert entry['registration_sha256'] == sha(C / 'registration.json')
assert entry['checker_sha256'] == sha(C / 'check-entry.py')
launcher = read(C / 'launcher-probe/completion-verification.json')
check_hashes(C / 'launcher-probe', launcher)
assert launcher['status'] == 'passed' and len(launcher['cases']) == 4
assert launcher['launcher_sha256'] == sha(C / 'run_pipeline.py')
assert launcher['checker_sha256'] == sha(C / 'check-launcher.py')
assert launcher['collector_registration_sha256'] == sha(C / 'registration.json')
assert all(x['cleanup'] and x['unrelated_job_alive'] for x in launcher['cases'])
for name in ('scale-training-registration.json', 'scale-verification-registration.json',
             'development-registration.json'):
    check_hashes(T, read(T / name))
for path, expected in read(T / 'development-registration.json')['original_harness_sha256'].items():
    assert sha(path) == expected, path
renewal = read(T / 'source-renewal-verification.json')
for dest, row in renewal['driver_changes'].items():
    assert sha(row['source']) == row['before_sha256']
    text = Path(row['source']).read_text()
    for before, after in row['allowed_replacements']:
        text = text.replace(before, after)
    assert Path(dest).read_text() == text and sha(dest) == row['after_sha256']
assert renewal['frozen_collector_modules_byte_identical'] == 15
assert renewal['stale_inherited_nested_harness_hashes_rejected'] == {}
renewal_entry = read(T / 'renewal-entry-verification.json')
assert renewal_entry['status'] == 'passed' and renewal_entry['driver_rebindings_checked'] == 15
assert renewal_entry['renewal_proof_sha256'] == sha(T / 'source-renewal-verification.json')
assert renewal_entry['checker_sha256'] == sha(T / 'check-renewal-entry.py')
native = read(T / 'native-probe/completion-verification.json')
check_hashes(T / 'native-probe', native)
assert native['status'] == 'passed'
assert [c['status'] for c in native['cases']] == ['verified', 'verification_error', 'verification_error']
development = read(T / 'development-entry-probe/completion-verification.json')
check_hashes(T / 'development-entry-probe', development)
assert development['status'] == 'passed'
assert development['registration_sha256'] == sha(T / 'development-registration.json')
checks = development['checks']
assert len(checks['original_admission_negative_cases']) == 32
assert all(v['rejected'] for v in checks['original_admission_negative_cases'].values())
assert checks['zero_head_whole_route']['outside_choices'] == 203
assert checks['source_and_candidate_bomb_contract_identical']
terminal = read(T / 'terminal-bomb-entry-verification.json')
assert terminal['status'] == 'passed' and len(terminal['nested_harness_negatives']) == 7
assert terminal['registration_sha256'] == sha(T / 'development-registration.json')
assert terminal['checker_sha256'] == sha(T / 'check-terminal-bomb-entry.py')
assert terminal['terminal']['natural_actions'] == 965
assert terminal['native_bomb_control_states'] == 15
assert sha(terminal['resolved_bomb_helper']['path']) == terminal['resolved_bomb_helper']['sha256']
assert terminal['resolved_bomb_helper']['matches_frozen_candidate_copy']
identity = read(T / 'protocol.json')['identity']
assert entry['runtime_identity'] == identity
assert native['engine_sha256'] == development['engine_sha256'] == terminal['terminal']['engine_sha256'] == identity['engine_sha256']
for item in (renewal_entry, development, terminal):
    assert item['new_mcts_calls'] == 0 and item['optimizer_updates'] == 0
assert sha(R / 'runs/prepare-e118-e119-20260920-01.py') == sha(T / 'preparation-source.py')

PUBLIC.mkdir()
sources = {'prepare-e118-e119.py': T / 'preparation-source.py',
           'publish-preparation.py': Path(__file__)}
for root, names, prefix in (
    (C, ('run_collections.py', 'check-entry.py', 'run_pipeline.py', 'check-launcher.py'), 'collector'),
    (T, ('scale_training.py', 'scale_verify.py', 'scale_development.py', 'candidate_original.py',
         'terminal_rng.py', 'bomb_extras.py', 'bomb_instances.py', 'check-renewal-entry.py',
         'prepare-native-probe.py', 'run-native-probe.py', 'check-development-entry.py',
         'check-terminal-bomb-entry.py'), 'training')):
    for name in names:
        sources[prefix + '/' + name] = root / name
source_hashes = {}
for name, source in sources.items():
    dest = PUBLIC / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    assert sha(source) == sha(dest)
    source_hashes[name] = sha(dest)
(PUBLIC / 'README.md').write_text(
    'These own-code snapshots preserve the E118/E119 source gates, fixed two-arm joint relic/card recipe and preparation controls under E116. '
    'They depend on the local frozen evidence/runtime layout and earlier collector modules; they are not standalone public runners. '
    'They contain no game JARs, model weights or raw traces.\n\n'
    'Preparation performs no training or new MCTS. The registered source and original gates must finish before continuation collection; '
    'both label audits must finish before fitting. Live and recorded originals require per-instance Bomb and twelve terminal RNG checks. '
    'A native helper may resolve through alignment/tests; the entry check records its actual path and verifies byte identity with the frozen helper.\n')
source_hashes['README.md'] = sha(PUBLIC / 'README.md')

collection = {'experiment': 'E118', 'status': 'preparation_complete', 'created_at': created,
    'protocol': read(C / 'protocol.json'), 'registration_sha256': sha(C / 'registration.json'),
    'entry_sha256': sha(C / 'entry-verification.json'),
    'execution_registration_sha256': sha(C / 'execution-registration.json'),
    'launcher_controls_sha256': sha(C / 'launcher-probe/completion-verification.json'),
    'launcher_cases': launcher['cases'], 'frozen_collector_modules_byte_identical': 15,
    'entry_known_source': entry['known_E116_source_replay'],
    'new_continuation_labels': 0, 'optimizer_updates': 0, 'collection_started': False,
    'limits': 'Prepared under the E116 engine. All E117 source and development original checks precede collection. No source results or learned gains in this report.'}
training = {'experiment': 'E119', 'status': 'preparation_complete', 'created_at': created,
    'protocol': read(T / 'protocol.json'), 'development_protocol': read(T / 'development-protocol.json'),
    'registrations': {name: sha(T / name) for name in ('scale-training-registration.json',
        'scale-verification-registration.json', 'development-registration.json')},
    'proofs': {name: sha(T / name) for name in ('source-renewal-verification.json',
        'renewal-entry-verification.json', 'native-probe/completion-verification.json',
        'development-entry-probe/completion-verification.json', 'terminal-bomb-entry-verification.json',
        'terminal-bomb-entry-attempt-01-error.json')},
    'driver_rebindings_checked': 15, 'same_collector_modules': 15,
    'inherited_stale_nested_hashes': 0, 'explicit_nested_hash_rejection_controls': 7,
    'native_choice_cases': native['cases'], 'outside_NN_choices_checked': 203,
    'candidate_selection_cases': checks['selection_order_cases'],
    'original_admission_rejection_cases': list(checks['original_admission_negative_cases']),
    'terminal_rng_streams_checked': len(terminal['terminal']['rng_streams']),
    'saved_natural_actions': 965, 'native_bomb_control_states': 15,
    'same_total_wrong_instances_rejected': True, 'wrong_countdown_rejected': True,
    'saved_natural_route_bomb_bearing_checks': 0,
    'helper_resolution_note': 'An initial checker expected the candidate directory. The native harness resolves a byte-identical stateless copy from alignment/tests; the corrected checker records the resolved path and validates code hashes. No comparator or game expectation changed.',
    'new_continuation_labels': 0, 'optimizer_updates': 0, 'new_mcts_calls': 0,
    'new_original_executions': 0, 'unseen_acceptance_games': 0,
    'own_source_hashes': source_hashes,
    'limits': 'Software preparation on saved E116 evidence, including a known-route zero-head fixture. This does not establish a learned gain, candidate native parity or population win rate. Source/label gates remain prerequisites.'}
write(D / 'e118-label-preparation.json', collection)
write(D / 'e119-training-preparation.json', training)
public_hashes = {str(p.relative_to(R)): sha(p) for p in sorted(PUBLIC.rglob('*')) if p.is_file()}
public_hashes.update({str(p.relative_to(R)): sha(p) for p in (D / 'e118-label-preparation.json', D / 'e119-training-preparation.json')})
publication = {'status': 'verified', 'created_at': created, 'identity': identity,
    'collector_registration_sha256': sha(C / 'registration.json'),
    'training_registration_sha256': sha(T / 'scale-training-registration.json'),
    'source_registration_sha256': sha(N / 'registration.json'),
    'public_hashes': public_hashes, 'raw_private_artifacts_published': False,
    'live_source_outcomes_read': False, 'formal_optimizer_updates': 0}
write(C / 'preparation-publication-verification.json', publication)
write(T / 'preparation-publication-verification.json', publication)
print({'status': 'verified', 'public_files': len(public_hashes),
       'publication_sha256': sha(T / 'preparation-publication-verification.json'),
       'collector_registration_sha256': sha(C / 'registration.json'),
       'training_registration_sha256': sha(T / 'scale-training-registration.json')})
