"""Publish scoped native ordering evidence and preserve the interrupted cohort."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil

Q = Path(__file__).resolve().parent
A = Q.parents[1]
R = A.parent / 'sts-rl-agent-pr'
N = R / 'runs/heart-e116-scale-source-refresh-20260920-01'
D = R / 'docs/experiments'
P = D / 'e120-diagnostic-sources'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


plan = read(Q / 'native-plan.json')
for path, expected in plan['harness_sha256'].items():
    assert sha(path) == expected, path
native = Q / 'original-controls/attempt-01'
done = read(native / 'completion.json')
assert done['all_executed'] and done['cases'] == 4
assert done['results_sha256'] == sha(native / 'results.json')
assert read(native / 'cleanup.json')['remaining'] == []
comparison = read(Q / 'original-before-comparison.json')
assert comparison['status'] == 'confirmed_difference' and comparison['fixture_imports'] == 4
assert comparison['mid_sequence_resynchronized'] is False
assert comparison['source_sha256'] == sha(native / 'results.json')
assert [r['status'] for r in comparison['results']] == ['mismatch', 'passed', 'passed', 'passed']
assert sum(len(r['steps']) for r in comparison['results']) == 11
differences = comparison['results'][0]['steps'][2]['differences']
assert set(differences) == {'draw_pile', 'discard_pile'}
assert [len(differences['draw_pile'][side]) for side in ('original', 'simulator')] == [4, 3]
assert [len(differences['discard_pile'][side]) for side in ('original', 'simulator')] == [4, 5]
rows = read(native / 'results.json')
assert [r['end_turn']['draws_beyond_normal_five'] for r in rows] == [0, 1, 0, 1]
stop = read(N / 'stop-verification.json')
assert stop['confirmed_diagnostic_sha256'] == sha(Q / 'original-before-comparison.json')
assert stop['saved_source_files'] == 1944 and stop['missing_source_files'] == 4200
assert not stop['invalid_source_files'] and not stop['missing_files_are_deaths']
assert stop['original_gate']['matched_routes'] == 10 and stop['original_gate']['matched_commands'] == 10205
assert stop['original_gate']['interrupted_seeds'] == [598511621]
assert stop['owned_source_and_original_process_groups_empty']
for name in ('heart-e116-scale-joint-labels-20260920-01', 'heart-e116-scale-training-20260920-01'):
    root = N.parent / name
    assert read(root / 'source-stop-verification.json')['source_stop_sha256'] == sha(N / 'stop-verification.json')
assert not (N.parent / 'heart-e116-scale-training-20260920-01/scale').exists()
assert not (N.parent / 'heart-e116-scale-joint-labels-20260920-01/joint').exists()
assert not P.exists()
P.mkdir()
sources = [Q / name for name in ('end-turn-order.cpp', 'original-diagnostic.py', 'compare-before.py', 'publish-diagnostic.py')]
sources += [N / 'stop-for-e120.py', N / 'finalize-external-stop.py']
for path in sources:
    shutil.copyfile(path, P / path.name)
    assert sha(path) == sha(P / path.name)
(P / 'README.md').write_text(
    'Own-code diagnostics and cohort accounting for E120. These scripts require the frozen local E116/E117 evidence layout '
    'and an owned game installation; they are not standalone public runners. No game source, JAR, weights or raw traces are included.\n\n'
    'The C++ diagnostic uses original-source-derived callback order as its comparison. Four separate original-game sequences then '
    'confirm the first Combust/No Draw/Runic Cube mismatch and three controls. Initial fixtures are explicit; subsequent cards and '
    'end-turn actions are replayed without restoration. This is not a natural-seed mismatch or learned win-rate result.\n')
diagnostic = {'experiment': 'E120', 'status': 'original_confirmed_pending_repair',
    'created_at': datetime.now(timezone.utc).isoformat(),
    'engine_sha256': comparison['engine_sha256'],
    'problem': 'Equal-priority player powers retain application order in the original. E116 stores ordinary powers by enum and always removes No Draw before Combust, losing the acquired order.',
    'trigger': 'Play Combust, then Battle Trance while holding Runic Cube; end the turn.',
    'original_result': 'Combust loses HP while No Draw is active, so Runic Cube cannot draw. The following normal turn draws five cards.',
    'simulator_result': 'No Draw is removed first; the Combust HP loss triggers an extra draw. That card is discarded before the following turn, changing both piles.',
    'native_cases': [{'name': r['spec']['name'], 'status': r['status'],
        'power_order_before_end': r['power_order_before_end'], 'end_turn': r['end_turn']} for r in rows],
    'commands': 11, 'native_comparison_statuses': [r['status'] for r in comparison['results']],
    'first_difference_step_zero_based': 2,
    'first_difference_counts': {'draw_pile': {'original': 4, 'simulator': 3},
                               'discard_pile': {'original': 4, 'simulator': 5}},
    'initial_fixture_imports': 4, 'mid_sequence_resynchronized': False,
    'source_regeneration_hypothesis_rejected': 'RegenPower actually queues RegenAction at the front. No add-to-back regeneration fix is justified by that source.',
    'repair_requirement': 'Retain native power application order and priority through stacking, removal/reapplication, snapshots, copy and observable state; execute end-turn callbacks in that order. Do not globally swap only No Draw and Combust, because the reverse-order control has a different correct result.',
    'original_comparison_sha256': sha(Q / 'original-before-comparison.json'),
    'source_plan_sha256': sha(Q / 'source-plan.json'), 'native_plan_sha256': sha(Q / 'native-plan.json'),
    'native_completion_sha256': sha(native / 'completion.json'),
    'optimizer_updates': 0, 'new_training_labels': 0,
    'limits': 'Four controlled battle sequences; only one ordering combination is a confirmed mismatch. No natural source winner is reported as divergent. E117 is stopped; E118/E119 remain closed pending repair and separately registered sources.'}
write(D / 'e120-end-turn-order-diagnostic.json', diagnostic)
public_stop = {k: v for k, v in stop.items() if k != 'source_index'}
public_stop['experiment'] = 'E117-stop-for-E120'
public_stop['stop_verification_sha256'] = sha(N / 'stop-verification.json')
write(D / 'e117-source-stop-result.json', public_stop)
hashes = {str(p.relative_to(R)): sha(p) for p in sorted(P.rglob('*')) if p.is_file()}
for name in ('e120-end-turn-order-diagnostic.json', 'e117-source-stop-result.json'):
    hashes[str((D / name).relative_to(R))] = sha(D / name)
proof = {'status': 'verified', 'public_hashes': hashes,
    'original_comparison_sha256': sha(Q / 'original-before-comparison.json'),
    'stop_verification_sha256': sha(N / 'stop-verification.json'), 'raw_private_artifacts_published': False}
write(Q / 'publication-verification.json', proof)
write(N / 'stop-publication-verification.json', proof)
print({'status': 'verified', 'matched_controls': 3, 'confirmed_native_differences': 1,
       'publication_sha256': sha(Q / 'publication-verification.json'),
       'saved_sources': stop['saved_source_files'], 'originals_matched': 10})
