"""Freeze E117's external-diagnostic stop without inventing a cohort mismatch."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

N = Path(__file__).resolve().parent
R = N.parents[1]
A = R.parent / 'ironclad-alignment'
S = N / 'natural'
Q = A / 'evidence/e117-development-parity-20260920-01'
D = A / 'evidence/e120-end-turn-order-diagnostic-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')


os.environ['HEART_BRANCH_RUNTIME'] = str(S)
os.environ['ALIGNMENT_BUILD'] = str(S / 'engine')
os.environ['STS_LIGHTSPEED_BUILD'] = str(S / 'engine')
sys.path.insert(0, str(S))
import run_refresh as F
F.S.verify_files(S)
stopped = read(N / 'external-diagnostic-stop.json')
assert stopped['status'] == 'stopped'
processes = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,pgid=,command='], text=True).splitlines()
for info in stopped['signaled']:
    assert not any(len(row.split()) >= 4 and row.split()[2] == str(info['process_group']) for row in processes)
assert read(N / 'source-execution.json')['exit_code'] == read(N / 'original-execution.json')['exit_code'] == 143
assert not (S / 'completion-verification.json').exists() and not (Q / 'completion-verification.json').exists()
roles, identity = read(S / 'seeds.json'), read(S / 'identity.json')
assigned = {seed: role for role, values in roles.items() for seed in values}
saved, invalid = [], []
for path in sorted((S / 'episodes').glob('*.json.gz')):
    seed = int(path.name.split('.')[0]); role = assigned[seed]
    reference = {'seed': seed, 'split': role, 'path': str(path.relative_to(S)), 'sha256': sha(path)}
    try:
        with gzip.open(path, 'rt') as stream:
            row = json.load(stream)
        if not F.valid(row, {'seed': seed}, identity):
            raise ValueError('source terminal/identity validity check failed: ' + str(row.get('status')))
        saved.append(dict(reference, status=row['status']))
    except Exception as error:
        invalid.append(dict(reference, error=str(error)))
audit = read(Q / 'source-development-audit.json')
assert audit['families'] == audit['terminal_replays'] == 512 and audit['execution_faults'] == 0
assert sha(Q / 'source-index.json') == audit['source_index_sha256']
assert sha(Q / 'source-audit-cases.json.gz') == audit['source_cases_sha256']
plan = read(Q / 'plan.json')
references = {r['seed']: r for r in read(Q / 'source-index.json')}
spec = importlib.util.spec_from_file_location('E117_stop_auditor', A / 'evidence/e81-development-winners-parity-20260919-01/verify.py')
auditor = importlib.util.module_from_spec(spec); spec.loader.exec_module(auditor)
results, commands = [], 0
for path in sorted((Q / 'controller-results').glob('*.json')):
    row = read(path)
    assert row['status'] == 'matched', 'preserve and investigate an actual cohort nonmatch separately'
    checked = auditor.audit_recorded(Q / f"recorded/{row['seed']}", references[row['seed']], identity)
    assert checked == row['verified']
    terminal = read(Q / f"terminal-rng/{row['seed']}.json")
    assert terminal == row['terminal_rng'] and terminal['status'] == 'matched'
    assert terminal['script_sha256'] == sha(Q / 'terminal_rng.py') and len(terminal['rng_streams']) == 12
    instance = read(Q / f"bomb-instances/{row['seed']}.json")
    assert instance == row['bomb_instances'] and instance['status'] == 'matched'
    assert instance['engine_sha256'] == identity['engine_sha256']
    assert instance['combiner_sha256'] == sha(Q / 'bomb_extras.py')
    assert instance['instance_checker_sha256'] == sha(Q / 'bomb_instances.py')
    assert instance['live_checks'] > 0 and instance['recorded_checks'] > 0
    assert instance['state_imports'] == 0 and instance['resynchronized'] is False
    assert instance['trace_sha256'] == terminal['trace_sha256'] and instance['rpc_sha256'] == terminal['rpc_sha256']
    commands += checked['commands']
    results.append({'seed': row['seed'], 'status': 'matched', 'commands': checked['commands'],
        'bomb_instances_sha256': sha(Q / f"bomb-instances/{row['seed']}.json"),
        'controller_result_sha256': sha(path), 'terminal_rng_sha256': sha(Q / f"terminal-rng/{row['seed']}.json")})
started = {int(p.parents[1].name.split('-')[0]) for p in (Q / 'original').glob('*/instance/last-launch.json')}
finished = {r['seed'] for r in results}
assert finished <= started <= set(plan['seeds'])
native = read(D / 'original-controls/attempt-01/completion.json')
assert native['all_executed'] and native['cases'] == 4
assert native['results_sha256'] == sha(D / 'original-controls/attempt-01/results.json')
assert read(D / 'original-controls/attempt-01/cleanup.json')['remaining'] == []
comparison = read(D / 'original-before-comparison.json')
assert comparison['status'] == 'confirmed_difference' and not comparison['mid_sequence_resynchronized']
assert [r['status'] for r in comparison['results']] == ['mismatch', 'passed', 'passed', 'passed']
summary = {'status': 'stopped_on_external_confirmed_rule_difference',
    'created_at': datetime.now(timezone.utc).isoformat(),
    'stop_at': stopped['finished_at'], 'source_registration_sha256': sha(N / 'registration.json'),
    'source_manifest_sha256': sha(S / 'manifest.json'), 'identity': identity,
    'source_complete': False, 'admit_labels': False,
    'saved_source_files': len(saved), 'files_by_role': {k: sum(r['split'] == k for r in saved) for k in roles},
    'invalid_source_files': invalid, 'missing_source_files': len(assigned) - len(saved) - len(invalid),
    'missing_files_are_deaths': False, 'source_index': saved, 'development_audit': audit,
    'original_gate': {'requested_winning_routes': len(plan['seeds']), 'original_executions_started': len(started),
        'matched_routes': len(results), 'matched_commands': commands,
        'interrupted_seeds': sorted(started - finished), 'unattempted_seeds': sorted(set(plan['seeds']) - started),
        'cohort_rules_mismatches_observed': 0, 'rows': results,
        'reason': 'External controlled rule mismatch, not an original mismatch on one of these natural routes.'},
    'confirmed_diagnostic_sha256': sha(D / 'original-before-comparison.json'),
    'original_diagnostic_completion_sha256': sha(D / 'original-controls/attempt-01/completion.json'),
    'owned_source_and_original_process_groups_empty': True,
    'stop_proof_sha256': sha(N / 'external-diagnostic-stop.json'),
    'new_labels': 0, 'optimizer_updates': 0, 'unseen_acceptance_games': 0,
    'limits': 'Partial source and six-or-fewer completed original routes are retained as scoped evidence. No full-source or original-cohort completion claim; 51/512 belongs to the fixed parent, not a learned candidate.'}
summary['limits'] = summary['limits'].replace('six-or-fewer completed', str(len(results)) + ' completed')
write(N / 'stop-verification.json', summary)
write(Q / 'external-stop-verification.json', {k: v for k, v in summary.items() if k != 'source_index'})
for folder in ('heart-e116-scale-joint-labels-20260920-01', 'heart-e116-scale-training-20260920-01'):
    closed = read(N.parent / folder / 'source-closed.json')
    assert closed['status'] == 'source_closed'
    assert closed['stop_proof_sha256'] == sha(N / 'external-diagnostic-stop.json')
    write(N.parent / folder / 'source-stop-verification.json', {
        'status': 'confirmed_source_closed_before_execution',
        'source_stop_sha256': sha(N / 'stop-verification.json'),
        'reason': 'E120 confirms end-turn power application order loss in Combust/No Draw/Runic Cube. E117 source remains incomplete and rejected.',
        'new_labels': 0, 'optimizer_updates': 0})
print({k: summary[k] for k in ('status', 'saved_source_files', 'files_by_role', 'invalid_source_files', 'missing_source_files')})
print({k: v for k, v in summary['original_gate'].items() if k not in ('rows', 'unattempted_seeds')})
