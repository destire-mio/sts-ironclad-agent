"""Admit E121 only after the registered natural and original integration."""
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
S = Q.parent / 'e116-bomb-instance-repair-20260920-01'
C, N, SEED = Q / 'candidate', Q / 'candidate-original', 1138994370
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
    return json.loads(gzip.decompress(p.read_bytes())) if p.suffix == '.gz' else json.loads(p.read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')

plan = read(Q / 'plan.json')
assert plan['selected_integration_seed'] == SEED
for name, expected in plan['before_source_files'].items():
    assert sha(S / 'source' / name) == expected, name
local = read(Q / 'local-verification.json')
assert local['status'] == 'passed' and local['full_ctest_cases'] == 279
assert local['portable_related_cases'] == 47 and local['source_files_matched'] == 90
for name, count in local['verification_groups'].items():
    assert f'100% tests passed out of {count}' in (Q / name).read_text()
assert read(Q / 'focused-after.json')['test_sha256'] == sha(A / 'tests/e121_power_order.cpp')
assert sha(A / 'tests/e121_power_order.cpp') == sha(R / 'sim_patch/alignment/tests/e121_power_order.cpp')
assert sha(A / 'tests/e121_power_snapshot.py') == sha(R / 'sim_patch/alignment/tests/e121_power_snapshot.py')
portable = read(Q / 'portable-application.json')
assert len(portable['source_files']) == 90
for name, expected in portable['source_files'].items():
    assert sha(Q / 'source' / name) == sha(Q / 'portable-source' / name) == expected
for name in ('original-order-after.json', 'portable-original-order-after.json'):
    proof = read(Q / name)
    assert proof['status'] == 'matched' and all(r['status'] == 'passed' for r in proof['results'])
    assert proof['order_comparisons'] == 38 and len(proof['snapshot_suffixes']) == 7
    assert proof['wrong_order_same_amount_rejected'] and proof['wrong_order_changes_next_draw']
    assert proof['order_checker_sha256'] == sha(Q / 'power_order.py')
    assert proof['checker_sha256'] == sha(Q / 'compare-controls.py')
    assert not proof['mid_sequence_resynchronized']
assert read(Q / 'original-bomb-after.json')['status'] == 'matched'
reg = read(Q / 'integration-registration.json')
for path, expected in reg['hashes'].items(): assert sha(path) == expected, path
assert read(Q / 'integration-stages-complete.json')['status'] == 'complete'
process = read(Q / 'pipeline-process-exit.json')
assert process['exit_code'] == 0 and process['cleanup']['clean']
assert not process['cleanup']['remaining_members']
cleanup = read(Q / 'integration-native-cleanup.json')['instances']
assert len(cleanup) == 1 and all(not row['remaining'] for row in cleanup)
identity = read(C / 'identity.json')
assert identity['engine_sha256'] == sha(C / 'engine/slaythespire.cpython-312-darwin.so') == local['engine_sha256']
assert identity['model_sha256'] == sha(C / 'model.pt') == 'cbeac10f84c7f719ec48405ceecd663442e76b66a92234f1b090e2cfc2acfef4'
for name, expected in read(C / 'manifest.json')['frozen_files'].items(): assert sha(C / name) == expected
completion = read(C / 'completion-verification.json')
assert completion['status'] == 'complete' and completion['zero_faults'] and completion['natural_terminals'] == 1
for name, expected in completion['hashes'].items(): assert sha(C / name) == expected
fresh, repeat = read(C / f'episodes/{SEED}.json.gz'), read(C / f'repeated/{SEED}.json.gz')
assert fresh['status'] == repeat['status'] == 'heart_win'
assert fresh['prefix'] == repeat['prefix'] and fresh['terminal_fingerprint'] == repeat['terminal_fingerprint']
report = read(C / 'report.json')
assert report['families'] == report['terminal_replays'] == len(report['winning_fresh_reruns']) == 1
assert report['execution_faults'] == 0 and report['identity'] == identity
assert report['winning_fresh_reruns'][0]['matched']
assert report['outside_choices_verified'] == sum(sum(row['outside_categories'].values()) for row in read(C / 'cases.json.gz'))
native = N / f'original/{SEED}-01'
result = read(native / 'result.json')
assert result['status'] == 'original_heart_trace_matched' and not result['resynchronized']
assert result['identity_sha256'] == sha(native / 'identity.json')
assert read(native / 'cleanup.json')['remaining'] == []
for path, expected in read(native / 'identity.json')['harness_sha256'].items(): assert sha(path) == expected
auditor_file = Q.parent / 'e81-development-winners-parity-20260919-01/verify.py'
spec = importlib.util.spec_from_file_location('e121_original_auditor', auditor_file)
auditor = importlib.util.module_from_spec(spec); spec.loader.exec_module(auditor)
route = auditor.audit_recorded(N / 'recorded', {'seed': SEED, 'sha256': sha(C / f'episodes/{SEED}.json.gz')}, identity)
assert route['hp'] == fresh['hp'] and route['commands'] == result['commands']
turn_checks = {}
for mode in ('original', 'recorded'):
    row = read(Q / (mode + '-turn-comparison.json'))
    assert row['status'] == 'matched' and row['checks'] > 0
    assert row['engine_sha256'] == identity['engine_sha256']
    assert row['combiner_sha256'] == sha(Q / 'turn_extras.py')
    assert row['order_checker_sha256'] == sha(Q / 'power_order.py')
    assert row['instance_checker_sha256'] == sha(Q / 'bomb_instances.py')
    assert 0 <= row['order_bearing_checks'] <= row['checks']
    assert row['state_imports'] == 0 and not row['resynchronized']
    turn_checks[mode] = row
terminal = read(Q / 'terminal-rng-verification.json')
assert terminal['status'] == 'matched' and not terminal['differences'] and len(terminal['rng_streams']) == 12
assert terminal['engine_sha256'] == identity['engine_sha256'] and terminal['state_imports'] == 0
assert terminal['script_sha256'] == sha(Q / 'audit-terminal-rng.py')
assert terminal['rpc_sha256'] == sha(native / 'rpc.jsonl.gz')
manifest = read(R / 'sim_patch/alignment/e121-power-order-manifest.json')
assert manifest['patch_sha256'] == sha(R / 'sim_patch/e121_power_order.patch') == portable['patch_sha256']
for item in manifest['files']:
    assert item['before'] == sha(S / 'source' / item['path'])
    assert item['after'] == sha(Q / 'source' / item['path'])
assert all(sha(A / 'simulator' / n) == h for n, h in plan['before_source_files'].items()), 'mutable source changed; preserve it'
for item in manifest['files']: shutil.copyfile(Q / 'source' / item['path'], A / 'simulator' / item['path'])
assert all(sha(A / 'simulator' / n) == h for n, h in portable['source_files'].items())

proof = {'experiment': 'E121', 'status': 'complete', 'finished_at': datetime.now(timezone.utc).isoformat(),
    **identity, 'baseline_engine_sha256': plan['before_engine_sha256'],
    'changed_source_files': [r['path'] for r in manifest['files']],
    'focused_before_failures': 11, 'focused_before_controls': 4, 'focused_after_passed': 15,
    'public_snapshot_binding_cases': 5, 'full_ctest_passed': 279, 'portable_related_checks': 47,
    'portable_source_files_matched': 90, 'original_order_sequences': 4, 'original_order_commands': 11,
    'original_order_checks_per_build': 38, 'snapshot_suffixes_and_clone_pairs': 7,
    'wrong_order_same_amount_rejected': True, 'wrong_order_changes_next_draw': True,
    'legacy_bomb_sequences': 4, 'legacy_bomb_commands': 23,
    'legacy_bomb_instance_checks': read(Q / 'original-bomb-after.json')['instance_comparisons'],
    'fresh_planner_outcome': fresh['status'], 'fresh_planner_repeat_matched': True,
    'fresh_outside_NN_choices_audited': report['outside_choices_verified'], 'original_route': route,
    'turn_order_checks': turn_checks, 'terminal_rng_streams_checked': 12,
    'terminal_rng_verification_sha256': sha(Q / 'terminal-rng-verification.json'),
    'patch_sha256': manifest['patch_sha256'], 'source_refresh_permitted': True,
    'old_engine_training_labels_permitted': False, 'optimizer_updates': 0, 'new_training_labels': 0,
    'rule': 'Native priority then stable application order; stack preserves position, removal erases it, reapplication gets a new position. Bomb instances share the order. Snapshot, copy and state text preserve order. Existing start, post-draw and end-turn callbacks use it.',
    'limits': 'Scoped player turn ordering and one preselected development Heart route. Not exhaustive game parity or a learned/unseen win rate. Full-route additive admission compares the three changed callback phases; other hook phases remain outside this repair. Berserk uses energy and scalar zero powers keep the existing presence semantics. mapRng internal state is not exported; map contents are checked. E117 stays stopped, E118/E119 closed.',
    'local_verification_sha256': sha(Q / 'local-verification.json'),
    'integration_registration_sha256': sha(Q / 'integration-registration.json')}
evidence = [Q / n for n in ('plan.json', 'local-verification.json', 'focused-after.json',
    'original-order-after.json', 'portable-original-order-after.json', 'original-bomb-after.json',
    'integration-registration.json', 'integration-stages-complete.json', 'pipeline-process-exit.json',
    'integration-native-cleanup.json', 'original-turn-comparison.json', 'recorded-turn-comparison.json',
    'terminal-rng-verification.json', 'candidate/manifest.json', 'candidate/completion-verification.json')]
proof['hashes'] = {str(p.relative_to(Q)): sha(p) for p in evidence}
write(Q / 'completion-verification.json', proof)
write(R / 'sim_patch/alignment/e121-power-order-report.json', {k: v for k, v in proof.items() if k != 'hashes'})
write(Q / 'publication-verification.json', {'status': 'verified',
    'completion_sha256': sha(Q / 'completion-verification.json'),
    'report_sha256': sha(R / 'sim_patch/alignment/e121-power-order-report.json'),
    'patch_sha256': manifest['patch_sha256']})
print({'status': 'complete', 'engine_sha256': identity['engine_sha256'], 'route': route})
