"""Publish only the prepared E124 execution wrapper and existing entry proof."""
from pathlib import Path
from datetime import datetime, timezone
import ast
import hashlib
import json
import shutil

T = Path(__file__).resolve().parent
R = T.parents[1]
D = R / 'docs/experiments'
P = D / 'e124-execution-sources'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
reg = read(T / 'training-execution-registration.json')
for path, expected in reg['hashes'].items():
    assert sha(path) == expected, path
entry = read(T / 'training-execution-entry-verification.json')
assert entry['status'] == 'passed' and entry['incomplete_inputs_rejected_before_execution']
assert entry['registration_sha256'] == sha(T / 'training-execution-registration.json')
assert entry['launcher_sha256'] == sha(T / 'run_training_pipeline.py')
assert entry['checker_sha256'] == sha(T / 'check-training-execution.py')
assert len(entry['inherited_exact_launcher_control_cases']) == 4 and entry['new_process_control_cases'] == 0
assert entry['new_mcts_calls'] == entry['optimizer_updates'] == entry['new_original_instances'] == 0
assert not any((T / name).exists() for name in ('execution', 'scale', 'original-candidates', 'training-execution.json'))
prepared = read(T / 'preparation-publication-verification.json')
for path, expected in prepared['public_hashes'].items():
    assert sha(R / path) == expected, path
assert not P.exists()
P.mkdir()
public_hashes = {}
for name in ('run_training_pipeline.py', 'check-training-execution.py', 'publish-execution.py'):
    ast.parse((T / name).read_text(), filename=name)
    shutil.copyfile(T / name, P / name)
    assert sha(T / name) == sha(P / name)
    public_hashes[str((P / name).relative_to(R))] = sha(P / name)
(P / 'README.md').write_text(
    'Own-code snapshots for the local E124 execution wrapper. They require the registered E122/E123 evidence, '
    'E124 prepared runtime and existing owned-process helper. They are not standalone runners. '
    'No game files, weights or raw traces are included.\n\n'
    'The wrapper runs both fixed fits, live heldout verification, each eligible natural/original gate and final selection in order. '
    'Every phase has an owned process group and subprocess allowance; existing internal deadlines stay unchanged. '
    'The 18-hour total is a scheduling deadline applied to each remaining subprocess allowance, not an independent outer OS watchdog. '
    'Entry validation and final native cleanup are synchronous. Completion requires cleanup. '
    'The actual full chain has not run because source and label admission remain pending.\n')
public_hashes[str((P / 'README.md').relative_to(R))] = sha(P / 'README.md')
report = {'experiment': 'E124-execution', 'status': 'preparation_complete',
    'created_at': datetime.now(timezone.utc).isoformat(), 'registration': reg,
    'registration_sha256': sha(T / 'training-execution-registration.json'),
    'entry_verification_sha256': sha(T / 'training-execution-entry-verification.json'),
    'incomplete_inputs_rejected_before_outputs': True,
    'inherited_process_cases': entry['inherited_exact_launcher_control_cases'],
    'inherited_launcher_proof_sha256': entry['inherited_launcher_probe_sha256'],
    'new_process_control_cases': 0, 'formal_pipeline_started': False,
    'new_mcts_calls': 0, 'optimizer_updates': 0, 'new_original_instances': 0,
    'production_adoption': False, 'unseen_acceptance_games': 0,
    'limits': 'Actual missing-input rejection and byte-identical inherited owned-process utility. No new positive full-chain execution, trained candidate or win-rate evidence.'}
path = D / 'e124-training-execution.json'
with path.open('x') as stream:
    json.dump(report, stream, indent=2)
    stream.write('\n')
public_hashes[str(path.relative_to(R))] = sha(path)
with (T / 'execution-publication-verification.json').open('x') as stream:
    json.dump({'status': 'verified', 'public_hashes': public_hashes,
        'registration_sha256': sha(T / 'training-execution-registration.json'),
        'entry_sha256': sha(T / 'training-execution-entry-verification.json'),
        'raw_private_artifacts_published': False, 'live_progress_read': False}, stream, indent=2)
    stream.write('\n')
print({'status': 'verified', 'public_files': len(public_hashes),
       'publication_sha256': sha(T / 'execution-publication-verification.json'),
       'formal_jobs_started': 0})
