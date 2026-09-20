"""Admit the E116 scoped repair only after full registered integration evidence."""
from pathlib import Path
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import shutil

Q = Path(__file__).resolve().parent
A = Q.parents[1]
R = A.parent / 'sts-rl-agent-pr'
P = Q.parent / 'e111-post-victory-exhaust-repair-20260920-01'
D = Q.parent / 'e115-bomb-instance-diagnostic-20260920-01'
C, N, seed = Q / 'candidate', Q / 'candidate-original', 1138994370
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
    return json.loads(gzip.decompress(p.read_bytes())) if p.suffix == '.gz' else json.loads(p.read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')

plan = read(Q / 'plan.json')
assert plan['selected_integration_seed'] == seed
assert plan['prior_diagnosis_sha256'] == sha(D / 'diagnostic-publication-verification.json')
for name, expected in plan['before_source_files'].items():
    assert sha(P / 'source' / name) == expected
paths = sorted(plan['before_source_files'])
assert len(paths) == 90
changed = [n for n in paths if sha(P / 'source' / n) != sha(Q / 'source' / n)]
assert changed == ['bindings/slaythespire.cpp', 'include/combat/Player.h', 'src/combat/Player.cpp']
portable = read(Q / 'portable-application.json')
assert portable['source_files_equal'] == 90
for name in paths:
    assert sha(Q / 'source' / name) == sha(Q / 'portable-source-v2' / name) == portable['source_files'][name]
before, after = read(Q / 'focused-before.json'), read(Q / 'focused-after.json')
assert before['source_sha256'] == after['source_sha256'] == sha(Q / 'e116_bomb_instances.cpp')
assert [r['case'] for r in before['results']] == [r['case'] for r in after['results']]
failed = {r['case'] for r in before['results'] if r['returncode'] != 0}
assert failed == {'double', 'mixed', 'block', 'equal_totals', 'clone', 'queued_clone', 'dead_guard'}
assert len(after['results']) == 11 and all(r['returncode'] == 0 for r in after['results'])
assert '100% tests passed out of 262' in (Q / 'ctest-full.log').read_text()
assert '100% tests passed out of 30' in (Q / 'portable-ctest-v2.log').read_text()
assert '100% tests passed out of 263' in (Q / 'ctest-full-with-snapshot.log').read_text()
assert '100% tests passed out of 31' in (Q / 'portable-ctest-with-snapshot.log').read_text()
snapshot = read(Q / 'snapshot-contract-verification.json')
assert snapshot['status'] == 'passed' and snapshot['constructed_binding_cases'] == 4
assert snapshot['script_sha256'] == sha(Q / 'e116_bomb_snapshot.py')
assert snapshot['results'] == [{'build': 'before', 'returncode': 1}, {'build': 'portable', 'returncode': 0}]
for name in ('original-after.json', 'portable-original-after.json'):
    control = read(Q / name)
    assert control['status'] == 'matched' and all(row['status'] == 'passed' for row in control['results'])
    assert len(control['results']) == 4 and len(control['snapshot_suffixes']) == 15
    assert control['instance_comparisons'] == 110 and control['wrong_multiplicity_rejected']
    assert control['missing_and_zero_countdowns_rejected'] and not control['mid_sequence_resynchronized']
    assert control['source_sha256'] == sha(D / 'original-controls/attempt-01/results.json')
    assert control['instance_checker_sha256'] == sha(Q / 'bomb_instances.py')
    assert control['checker_sha256'] == sha(Q / 'compare-controls.py')
assert read(D / 'original-controls/attempt-01/cleanup.json')['remaining'] == []
for path, expected in read(Q / 'integration-registration.json')['hashes'].items():
    assert sha(path) == expected, path
stages = read(Q / 'integration-stages-complete.json')
exit_proof = read(Q / 'pipeline-process-exit.json')
assert stages['status'] == 'complete' and exit_proof['exit_code'] == 0
assert exit_proof['cleanup']['clean'] and not exit_proof['cleanup']['remaining_members']
assert all(not row['remaining'] for row in read(Q / 'integration-native-cleanup.json')['instances'])
assert len(read(Q / 'integration-native-cleanup.json')['instances']) == 1
identity = read(C / 'identity.json')
assert identity['engine_sha256'] == sha(C / 'engine/slaythespire.cpython-312-darwin.so') == sha(Q / 'build/slaythespire.cpython-312-darwin.so')
assert identity['model_sha256'] == sha(C / 'model.pt') == 'cbeac10f84c7f719ec48405ceecd663442e76b66a92234f1b090e2cfc2acfef4'
for name, expected in read(C / 'manifest.json')['frozen_files'].items(): assert sha(C / name) == expected
completion = read(C / 'completion-verification.json')
assert completion['status'] == 'complete' and completion['zero_faults'] and completion['natural_terminals'] == 1
for name, expected in completion['hashes'].items(): assert sha(C / name) == expected
fresh, repeated = read(C / f'episodes/{seed}.json.gz'), read(C / f'repeated/{seed}.json.gz')
assert fresh['status'] == repeated['status'] == 'heart_win'
assert fresh['prefix'] == repeated['prefix'] and fresh['terminal_fingerprint'] == repeated['terminal_fingerprint']
report = read(C / 'report.json')
assert report['families'] == report['terminal_replays'] == len(report['winning_fresh_reruns']) == 1
assert report['execution_faults'] == 0 and report['identity'] == identity
assert report['winning_fresh_reruns'][0]['matched']
assert report['winning_fresh_reruns'][0]['sha256'] == sha(C / f'repeated/{seed}.json.gz')
assert report['outside_choices_verified'] == sum(sum(row['outside_categories'].values()) for row in read(C / 'cases.json.gz'))
native = N / f'original/{seed}-01'
result = read(native / 'result.json')
assert result['status'] == 'original_heart_trace_matched' and not result['resynchronized']
assert result['identity_sha256'] == sha(native / 'identity.json') and read(native / 'cleanup.json')['remaining'] == []
for path, expected in read(native / 'identity.json')['harness_sha256'].items(): assert sha(path) == expected
helper = Q.parent / 'e81-development-winners-parity-20260919-01/verify.py'
spec = importlib.util.spec_from_file_location('e116_original_auditor', helper)
auditor = importlib.util.module_from_spec(spec); spec.loader.exec_module(auditor)
route = auditor.audit_recorded(N / 'recorded', {'seed': seed, 'sha256': sha(C / f'episodes/{seed}.json.gz')}, identity)
assert route['hp'] == fresh['hp'] and route['commands'] == result['commands']
for label in ('original', 'recorded'):
    row = read(Q / (label + '-bomb-comparison.json'))
    assert row['status'] == 'matched' and row['checks'] > 0 and row['engine_sha256'] == identity['engine_sha256']
    assert row['instance_checker_sha256'] == sha(Q / 'bomb_instances.py')
    assert row['combiner_sha256'] == sha(Q / 'bomb_extras.py')
    assert row['state_imports'] == 0 and not row['resynchronized']
terminal = read(Q / 'terminal-rng-verification.json')
assert terminal['status'] == 'matched' and not terminal['differences'] and len(terminal['rng_streams']) == 12
assert terminal['engine_sha256'] == identity['engine_sha256'] and terminal['state_imports'] == 0
assert terminal['script_sha256'] == sha(Q / 'audit-terminal-rng.py')
assert terminal['rpc_sha256'] == sha(native / 'rpc.jsonl.gz')
manifest = read(R / 'sim_patch/alignment/e116-bomb-instance-manifest.json')
assert manifest['patch_sha256'] == sha(R / 'sim_patch/e116_bomb_instances.patch') == portable['patch_sha256']
assert manifest['files'] == [{'path': name, 'before': sha(P / 'source' / name), 'after': sha(Q / 'source' / name)} for name in changed]

# Publish the checked source to the mutable working copy, preserving any
# unexpected edits by refusing an unrecognized before state.
assert all(sha(A / 'simulator' / name) == plan['before_source_files'][name] for name in paths)
for name in changed: shutil.copyfile(Q / 'source' / name, A / 'simulator' / name)
assert all(sha(A / 'simulator' / name) == sha(Q / 'source' / name) for name in paths)
for name in ('e116_bomb_instances.cpp', 'bomb_instances.py', 'e116_bomb_snapshot.py'):
    shutil.copyfile(Q / name, A / 'tests' / name)
    assert sha(Q / name) == sha(R / 'sim_patch/alignment/tests' / name)
cmake = A / 'CMakeLists.txt'
addition = (R / 'sim_patch/alignment/CMakeLists.txt').read_text().split('\nadd_executable(e116_bomb_instance_tests')[1]
assert 'e116_bomb_instance_tests' not in cmake.read_text()
cmake.write_text(cmake.read_text() + '\nadd_executable(e116_bomb_instance_tests' + addition)

files = {p for p in Q.iterdir() if p.is_file() and p.suffix in ('.py', '.json', '.log', '.cpp')
         and p.name != 'observation-schedule.json'}
for subtree in ('candidate', 'candidate-original'):
    files |= {p for p in (Q / subtree).rglob('*') if p.is_file() and 'instance' not in p.parts
              and 'source' not in p.parts and p.suffix in ('.py', '.json', '.gz', '.log', '.jsonl')
              and p.name != 'status.json'}
proof = {'experiment': 'E116', 'status': 'complete', 'finished_at': datetime.now(timezone.utc).isoformat(), **identity,
    'baseline_engine_sha256': plan['before_engine_sha256'], 'changed_source_files': changed,
    'focused_before_failures': 7, 'focused_before_controls': 4, 'focused_after_passed': 11,
    'full_ctest_passed': 263, 'portable_focused_including_E110_E111': 31, 'portable_source_files_matched': 90,
    'public_snapshot_binding_cases': 4,
    'original_control_sequences': 4, 'original_control_commands': 23,
    'original_control_before_mismatches': 2, 'original_control_after_matches': 4,
    'per_build_control_instance_comparisons': 110, 'snapshot_suffixes_and_clone_pairs': 15,
    'wrong_equal_total_multiplicity_rejected': True, 'invalid_countdown_rejected': True,
    'fresh_planner_outcome': fresh['status'], 'fresh_planner_repeat_matched': True,
    'fresh_outside_NN_choices_audited': report['outside_choices_verified'], 'original_route': route,
    'full_original_instance_checks': read(Q / 'original-bomb-comparison.json'),
    'full_recorded_instance_checks': read(Q / 'recorded-bomb-comparison.json'),
    'terminal_rng_streams_checked': 12, 'terminal_rng_verification_sha256': sha(Q / 'terminal-rng-verification.json'),
    'original_auditor_sha256': sha(helper), 'patch_sha256': manifest['patch_sha256'],
    'optimizer_updates': 0, 'new_training_labels': 0, 'source_refresh_permitted': True,
    'old_engine_training_labels_permitted': False,
    'rule': 'Every Bomb owns countdown and damage. Deferred reductions use branch-local IDs and each expiry queues its own hit. Snapshot, copy, state text and instance export retain multiplicity. Legacy totals are derived, not a second state.',
    'build_note': 'Initial git apply under the outer checkout skipped unprefixed files; the source-hash gate rejected it and its seven expected test failures are preserved. A new portable source/build applied the same patch with explicit cwd and matched all ninety files before compilation.',
    'limits': 'Scoped Bomb repair and one preselected development integration route, not exhaustive original parity or learned/population success. Relative callback order of distinct power types is outside this repair. Native mapRng state is not exported; route map contents are checked. E112 remains stopped and E113/E114 remain closed.',
    'hashes': {str(p.relative_to(Q)): sha(p) for p in sorted(files)}}
write(Q / 'completion-verification.json', proof)
public = {k: v for k, v in proof.items() if k != 'hashes'}
write(R / 'sim_patch/alignment/e116-bomb-instance-report.json', public)
write(Q / 'publication-verification.json', {'status': 'verified',
    'repair_proof_sha256': sha(Q / 'completion-verification.json'),
    'report_sha256': sha(R / 'sim_patch/alignment/e116-bomb-instance-report.json'),
    'manifest_sha256': sha(R / 'sim_patch/alignment/e116-bomb-instance-manifest.json'),
    'patch_sha256': manifest['patch_sha256']})
print({k: proof[k] for k in ('status', 'engine_sha256', 'full_ctest_passed', 'fresh_outside_NN_choices_audited', 'original_route')})
