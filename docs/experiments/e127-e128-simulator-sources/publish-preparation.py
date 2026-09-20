"""Publish simulator-only study metadata and authored drivers, without run data."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

T = Path(__file__).resolve().parent
R = T.parents[1]
C = R / 'runs/heart-e121-simulator-joint-labels-20260920-01'
N = R / 'runs/heart-e121-scale-source-refresh-20260920-01'
D = R / 'docs/experiments'
DEST = D / 'e127-e128-simulator-sources'
read = lambda p: json.loads(p.read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def copy(source, relative):
    destination = DEST / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    assert sha(source) == sha(destination)


stop = read(N / 'original-stop-verification.json')
assert stop['status'] == 'stopped_by_user_scope_change' and stop['native_jvms_remaining'] == 0
for name, digest in stop['hashes'].items():
    assert sha(N / name) == digest
entry = read(C / 'entry-verification.json')
controls = read(C / 'simulator-admission-probe/completion-verification.json')
owner = read(C / 'launcher-probe/completion-verification.json')
training_entry = read(T / 'training-execution-entry-verification.json')
launch = read(T / 'study-launch-verification.json')
diff = read(T / 'preparation-diff.json')
assert entry['status'] == 'complete' and controls['status'] == owner['status'] == training_entry['status'] == 'passed'
assert len(diff['frozen_collector_modules_identical']) == 15
assert len(diff['fit_and_live_choice_rebind_only']) == 2
assert launch['status'] == 'launched_waiting_for_source'
assert sha(T / 'study-registration.json') == launch['study_registration_sha256']
assert not DEST.exists()
DEST.mkdir()
for root, subdir, files in [
    (C, 'collector', ('run_collections.py', 'run_pipeline.py', 'check-entry.py', 'check-launcher.py',
        'check-simulator-admission.py', 'protocol.json', 'registration.json', 'execution-registration.json')),
    (T, 'training', ('scale_training.py', 'scale_verify.py', 'scale_development.py', 'run_training_pipeline.py',
        'run_study.py', 'check-training-execution.py', 'protocol.json', 'scale-training-registration.json',
        'scale-verification-registration.json', 'development-protocol.json', 'development-registration.json',
        'training-execution-registration.json', 'study-registration.json')),
]:
    for name in files: copy(root / name, subdir + '/' + name)
copy(R / 'runs/prepare-e127-e128-simulator-study.py', 'prepare-study.py')
copy(Path(__file__), 'publish-preparation.py')
write(DEST / 'unchanged-collector-modules.json', diff['frozen_collector_modules_identical'])
(DEST / 'README.md').write_text(
    '# E127/E128 simulator-only study\n\n'
    'The user paused original-game alignment. These drivers preserve the frozen E121 engine, '
    '6144 family roles, all simulator replay/RNG/NN audits, and both fixed training recipes. '
    'Native source and candidate gates are removed; no native launcher remains on this execution path.\n\n'
    'The 15 inherited collector modules are unchanged and identified by hash. Local runtime, model and '
    'source artifacts referenced by the manifests are required to execute these archived drivers. '
    'The archive contains no game JAR, model weights or raw routes.\n\n'
    'The local study controller waits for complete source proof on a 20-minute cadence, runs all '
    'continuation collection and audits, then both fits and qualifying natural development screens. '
    'It does not draw unseen seeds or claim original-game performance.\n')
snapshot = read(N / 'observation-20260920T111136.json')
report = {'experiment': 'E127-E128', 'recorded_at': datetime.now(timezone.utc).isoformat(),
    'status': 'launched_waiting_for_source', 'evidence_scope': 'simulator_only',
    'user_instruction': '先不考虑不一致的情况',
    'scope_amendment': read(N / 'user-scope-amendment.json'),
    'original_job_stop': {'exit_code': stop['exit_code'], 'owned_processes_clean': stop['owned_processes_clean'],
        'native_instances_clean': stop['native_instances_clean'], 'native_jvms_remaining': 0,
        'verified_at': stop['verified_at'], 'proof_sha256': sha(N / 'original-stop-verification.json')},
    'source_checkpoint': {'observed_at': snapshot['observed_at'], 'saved_files': snapshot['source_files'],
        'requested_families': 6144, 'active_workers': snapshot['source_status']['active_workers'],
        'controller_os_verified_live': snapshot['processes']['source']['live'],
        'snapshot_sha256': sha(N / 'observation-20260920T111136.json')},
    'launch': launch, 'identity': read(C / 'protocol.json')['identity'],
    'families': read(C / 'protocol.json')['families'], 'small_fit_families': 1536,
    'expanded_fit_families': 4608, 'joint_decisions': ['first Boss relic', 'scoped Act2 card choice'],
    'fit_steps_per_arm': 1000, 'fixed_fit_config': read(T / 'protocol.json')['config'],
    'unchanged_collector_modules': 15, 'fit_and_live_verification_rebind_only': True,
    'checks': {'actual_incomplete_source_rejected_before_outputs': True,
        'known_source_first_relic_replayed': entry['known_E121_source_replay'],
        'simulator_admission_cases': controls['cases'], 'owned_process_cases': owner['cases'],
        'training_incomplete_input_rejected': training_entry['incomplete_inputs_rejected_before_execution']},
    'paused_alignment': ['E125 native diagnosis', 'E126 isolated candidate before adoption'],
    'superseded_unstarted_studies': ['E123', 'E124'],
    'new_labels': 0, 'optimizer_updates': 0, 'unseen_acceptance_games': 0,
    'limits': 'A launched dependency chain waiting for source completion. Simulator-only scope does not establish original-game parity. Preparation and partial source counts are not a learned gain or unseen acceptance.',
    'source_archive': {str(p.relative_to(R)): sha(p) for p in sorted(DEST.rglob('*')) if p.is_file()}}
write(D / 'e127-e128-simulator-training-launch.json', report)
write(T / 'preparation-publication-verification.json', {'status': 'published',
    'report_sha256': sha(D / 'e127-e128-simulator-training-launch.json'),
    'source_archive_files': len(report['source_archive']), 'study_launch_sha256': sha(T / 'study-launch-verification.json')})
print({'published': str(D / 'e127-e128-simulator-training-launch.json'), 'source_files': len(report['source_archive'])})
