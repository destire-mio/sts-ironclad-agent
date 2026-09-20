"""Freeze one registered development route after local repair checks."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess

Q = Path(__file__).resolve().parent
A = Q.parents[1]
S = Q.parent / 'e116-bomb-instance-repair-20260920-01'
C = Q / 'candidate'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')

assert '100% tests passed out of 262' in (Q / 'ctest-existing.log').read_text()
assert '100% tests passed out of 16' in (Q / 'focused-after-v2.log').read_text()
assert '100% tests passed out of 1' in (Q / 'ctest-e94.log').read_text()
assert '100% tests passed out of 47' in (Q / 'portable-ctest.log').read_text()
before = read(Q / 'focused-before-v2.json')
assert len(before) == 15 and sum(r['exit_code'] != 0 for r in before) == 11
after = []
for row in before:
    proc = subprocess.run([str(Q / 'build/e121_power_order_tests'), row['case']], text=True, capture_output=True)
    after.append(dict(case=row['case'], exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr))
assert all(row['exit_code'] == 0 for row in after)
write(Q / 'focused-after.json', {'test_sha256': sha(A / 'tests/e121_power_order.cpp'), 'results': after})

for label in ['original-order-after.json', 'portable-original-order-after.json']:
    result = read(Q / label)
    assert result['status'] == 'matched' and len(result['results']) == 4
    assert result['order_comparisons'] == 38 and len(result['snapshot_suffixes']) == 7
    assert result['wrong_order_same_amount_rejected'] and result['wrong_order_changes_next_draw']
    assert result['order_checker_sha256'] == sha(Q / 'power_order.py')
assert read(Q / 'original-bomb-after.json')['status'] == 'matched'
for n, h in read(Q / 'portable-application.json')['source_files'].items():
    assert sha(Q / 'source' / n) == sha(Q / 'portable-source' / n) == h
names = lambda p: {t['name'] for t in json.loads(subprocess.check_output(
    ['ctest', '--test-dir', str(p), '--show-only=json-v1']))['tests']}
old, new = names(S / 'build'), names(Q / 'build')
assert not old - new and len(new) == 279 and len(new - old) == 16
write(Q / 'local-verification.json', {
    'status': 'passed', 'full_ctest_cases': 279, 'existing_case_names_preserved': len(old),
    'verification_groups': {'ctest-existing.log': 262, 'focused-after-v2.log': 16, 'ctest-e94.log': 1},
    'portable_related_cases': 47, 'source_files_matched': 90,
    'focused_before_failures': 11, 'focused_before_controls': 4, 'focused_after_passed': 15,
    'binding_cases': 5, 'controlled_native_sequences': 4, 'controlled_native_commands': 11,
    'order_checks': 38, 'snapshot_clone_suffixes': 7,
    'legacy_bomb_sequences': 4, 'legacy_bomb_commands': 23,
    'fixture_corrections': 'Invalid initial post-draw hypothesis removed before repair testing; global diagnostic sum is not branch state. Logs retained.',
    'cmake_entry_correction': 'Local CMake omitted the existing E94 terminal test. Added the unchanged public entry, ran that case, and checked all 263 original case names.',
    'portable_dependency_correction': 'Initial build lacked JSON_INCLUDE. Configured the known header directory and rebuilt; source patch unchanged.',
    'engine_sha256': sha(Q / 'build/slaythespire.cpython-312-darwin.so'),
    'portable_engine_sha256': sha(Q / 'portable-build/slaythespire.cpython-312-darwin.so')})

for n, h in read(S / 'candidate/manifest.json')['frozen_files'].items():
    assert sha(S / 'candidate' / n) == h, n
C.mkdir()
names = [n for n in read(S / 'candidate/manifest.json')['frozen_files']
         if n.startswith('source/') or n == 'model.pt']
names += ['heart_branch_pilot.py', 'heart_branch_training.py', 'heart_combat_development.py',
          'heart_play_selected.py', 'run_refresh.py', 'config.json', 'seeds.json']
for name in names:
    target = C / name; target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(S / 'candidate' / name, target)
assert read(C / 'seeds.json') == {'fit': [], 'label_holdout': [], 'train_development': [1138994370]}
(C / 'engine').mkdir()
engine = C / 'engine/slaythespire.cpython-312-darwin.so'
shutil.copyfile(Q / 'build' / engine.name, engine)
write(C / 'identity.json', {'engine_sha256': sha(engine), 'model_sha256': sha(C / 'model.pt')})
write(C / 'plan.json', {'experiment': 'E121-integration', 'created_at': datetime.now(timezone.utc).isoformat(),
    'repair_plan_sha256': sha(Q / 'plan.json'), 'source_runtime': str(S / 'candidate'),
    'selection': '1138994370 fixed in E121 plan before candidate outcomes; no replacements.',
    'long_job_observation_interval_seconds': 1200,
    'verification': 'Parent outside NN and MCTS, terminal replay and all outside choices; winner replanned; native route with Bomb and turn-power order checks; twelve terminal RNGs.',
    'limits': 'Known development route, no optimization or unseen acceptance. E117 stopped; E118/E119 closed.'})
shutil.copyfile(__file__, C / 'preparation-source.py')
write(C / 'manifest.json', {'frozen_files': {str(p.relative_to(C)): sha(p)
    for p in sorted(C.rglob('*')) if p.is_file()}})

prior = read(S / 'integration-registration.json')
hashes = {p: h for p, h in prior['hashes'].items() if not p.startswith(str(S))}
for p, h in hashes.items(): assert sha(p) == h, p
for name in ['plan.json', 'prepare-integration.py', 'local-verification.json', 'integrate.py',
        'prepare-recorded.py', 'audit-terminal-rng.py', 'turn_extras.py', 'power_order.py',
        'bomb_instances.py', 'candidate/manifest.json', 'original-order-after.json',
        'portable-original-order-after.json']:
    hashes[str(Q / name)] = sha(Q / name)
# verify_heart_winners puts A/tests first, where the stateless Bomb helper is identical.
assert sha(A / 'tests/bomb_instances.py') == sha(Q / 'bomb_instances.py')
hashes[str(A / 'tests/bomb_instances.py')] = sha(A / 'tests/bomb_instances.py')
write(Q / 'integration-registration.json', {
    'experiment': 'E121-integration', 'registered_at': datetime.now(timezone.utc).isoformat(),
    'owned_launcher': prior['owned_launcher'], 'wrapper_seconds': 2400,
    'stage_seconds': prior['stage_seconds'], 'long_job_observation_interval_seconds': 1200,
    'order_admission_scope': 'Each of the three modified turn callback phases. Non-callback power ordering is recorded in state but does not block phase admission.',
    'hashes': hashes})
print({'status': 'registered', **read(C / 'identity.json'), 'local_cases': 279, 'portable_cases': 47})
