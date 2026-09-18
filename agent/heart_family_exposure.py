#!/usr/bin/env python3
"""Conditional exposure-matched follow-up to the completed E34 data comparison."""
import argparse
import copy
import math
from pathlib import Path
import shutil

import heart_data_scale as E
import heart_data_scale_audit as V

P, H, R, S, T, L = E.P, E.H, E.R, E.S, E.T, E.L


def prepare(root, source):
    """No new outcomes or updates: require the E34 comparison to have finished."""
    assert not root.exists()
    decision = H.read_json(source / 'decision.json')
    assert decision['status'] == 'complete'
    assert decision['selected_for_fresh_acceptance'] is None, 'finish a passing candidate acceptance first'
    original = source / 'expanded'
    S.verify_files(original)
    proof = H.read_json(original / 'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, sha in proof['hashes'].items():
        assert S.sha(original / name) == sha
    E.copy_runtime(original, root)
    for name in ('identity.json', 'roots.json.gz', 'branch-labels.json', 'results-index.json',
                 'seed-roles.json', 'seeds.json', 'references.json', 'collection-report.json'):
        shutil.copy2(original / name, root / name)
    shutil.copy2(__file__, root / 'run_family_exposure.py')
    shutil.copy2(V.__file__, root / 'verify_data_scale.py')
    shutil.copy2(E.__file__, root / 'heart_data_scale.py')
    shutil.copy2(V.__file__, root / 'heart_data_scale_audit.py')
    old_training = H.read_json(original / 'training-report.json')
    small_training = H.read_json(source / 'small/training-report.json')
    steps = math.ceil(old_training['optimizer_updates'] * old_training['mixed_fit_families']
        / small_training['mixed_fit_families'])
    assert steps == 5658
    previous = H.torch.load(original / 'candidate.pt', map_location='cpu', weights_only=True)
    plan = copy.deepcopy(H.read_json(original / 'plan.json'))
    plan.update(experiment='E35', created_at=P.utc(), source_comparison=str(source),
        source_decision_sha256=S.sha(source / 'decision.json'), label_evidence_root=str(source),
        intervention='Same expanded corpus, initialization, optimizer, learning rate, KL, batches and RNG. Normalize update count by independent mixed-fit family count: ceil(2000*99/35)=5658. No new labels or seed roles.',
        hypothesis='The larger corpus received fewer optimization exposures per family at the same 2000-step budget. This test addresses that underfitting possibility without claiming that more data alone improved performance.',
        evaluation_role='Same 1024 E23 training development roots with verified E32 baseline; not unseen acceptance',
        stopping_rule='One exposure-matched final checkpoint, no step sweep or best-checkpoint selection. Compare local fit, the same 280 full-legal holdout choices, and complete development games. Retain the 63 wins / at most 10 lost baseline wins gate. A failed fitting target cannot rule out all optimization choices; do not repeatedly add steps under the same hypothesis.',
        interpretation='Near-complete fitting of the original training-label pairs (accuracy >=0.98, excluding diagnostic supplement labels) without held-out or whole-game improvement argues against insufficient updates as the sole explanation for E34. Preserve alternative explanations, including representation/generalization and policy-continuation changes.',
        limits='This adds optimization compute to the expanded-data recipe. It is not an equal-compute data-size comparison. Holdout roots were seen by the base model; only a later fresh frozen-policy test estimates unseen success. Original Java parity incomplete; Prismatic Shard excluded.')
    plan['training'].update(steps=steps, record_state_hash_at_steps=[2000, steps],
        expected_state_hashes={'2000': previous['state_hash']})
    plan['control_2000_step_state_hash'] = previous['state_hash']
    plan['control_2000_step_checkpoint_sha256'] = S.sha(original / 'candidate.pt')
    H.write_json(root / 'plan.json', plan)
    E.freeze(root)
    print({'status': 'prepared', 'steps': steps, 'old_mixed_fit_families': 35,
        'expanded_mixed_fit_families': 99, 'required_2000_step_state_hash': previous['state_hash']}, flush=True)


def train(root):
    L.verify_runtime(root)
    T.train(root)
    plan, report = H.read_json(root / 'plan.json'), H.read_json(root / 'training-report.json')
    matches = [e for e in report['history'] if e['step'] == 2000]
    assert len(matches) == 1 and matches[0]['state_hash'] == plan['control_2000_step_state_hash']
    H.write_json(root / 'optimizer-prefix-verification.json', {'status': 'complete',
        'matched_step': 2000, 'state_hash': matches[0]['state_hash'],
        'control_checkpoint_sha256': plan['control_2000_step_checkpoint_sha256'],
        'final_updates': report['optimizer_updates'], 'new_labels': 0,
        'training_report_sha256': S.sha(root / 'training-report.json')})


def finish(root):
    S.verify_files(root)
    assert not (root / 'decision.json').exists()
    proof = H.read_json(root / 'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, sha in proof['hashes'].items():
        assert S.sha(root / name) == sha
    prefix = H.read_json(root / 'optimizer-prefix-verification.json')
    training = H.read_json(root / 'training-report.json')
    assert prefix['status'] == 'complete' and prefix['final_updates'] == training['optimizer_updates'] == 5658
    assert prefix['training_report_sha256'] == S.sha(root / 'training-report.json')
    report = H.read_json(root / 'report.json')
    full = H.read_json(root / 'full-choice-report.json')
    assert full['candidate_sha256'] == training['checkpoint_sha256'] == S.sha(root / 'candidate.pt')
    passed = proof['development_gate_passed']
    result = {'experiment': 'E35', 'status': 'complete', 'finished_at': P.utc(),
        'optimizer_updates': training['optimizer_updates'], 'optimizer_prefix_verified': True,
        'candidate_sha256': training['checkpoint_sha256'],
        'local_fit_pair_accuracy': training['after']['fit']['pair_accuracy'],
        'local_fit_target_met': training['after']['fit']['pair_accuracy'] >= .98,
        'fit_pair_accuracy_including_diagnostic_supplements': full['metrics']['fit']['pair_accuracy'],
        'common_holdout_winning_choices': full['metrics']['label_holdout']['full_legal_choice_wins_among_labelled'],
        'baseline_wins': report['baseline_wins'], 'candidate_wins': report['candidate_wins'],
        'paired': report['paired'], 'development_gate_passed': passed,
        'selected_for_fresh_acceptance': root.name if passed else None,
        'new_acceptance_seeds': 0, 'promoted_deployed_policy': False,
        'report_sha256': S.sha(root / 'report.json'),
        'verification_sha256': S.sha(root / 'completion-verification.json'),
        'limits': H.read_json(root / 'plan.json')['limits']}
    H.write_json(root / 'decision.json', result)
    (root / '训练次数结果.md').write_text(
        '# E35：匹配每个有效家庭的训练次数\n\n'
        '使用 E34 的扩展数据，从原模型进行 5,658 次更新。第 2,000 步的全部权重与 E34 扩展组相同；'
        '没有新增标签、挑选中间模型或调整开发门槛。\n\n'
        f'拟合状态的动作对准确率：{result["local_fit_pair_accuracy"]:.4%}。'
        f'共同 280 个留出局面的获胜选择：{result["common_holdout_winning_choices"]}，原模型为 56。\n\n'
        f'同一 1,024 个历史训练开发根：原模型 {report["baseline_wins"]} 胜，候选 {report["candidate_wins"]} 胜；'
        f'配对结果 {report["paired"]}。开发门槛通过：{passed}。\n\n'
        '终局重放、获胜路线、NN 选择与新规划复验见 completion-verification.json。'
        '这些不是未见种子成绩；原版 Java 一致性保持 INCOMPLETE。\n')
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train', 'resolve', 'evaluate', 'verify', 'finish'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root, args.source.resolve())
    elif args.command == 'train':
        train(root)
    elif args.command == 'resolve':
        assert not (root / 'full-choice-report.json').exists()
        L.resolve_choices(root)
    elif args.command == 'evaluate':
        assert not (root / 'report.json').exists()
        L.evaluate(root)
    elif args.command == 'verify':
        V.evaluation(root)
    else:
        finish(root)
