#!/usr/bin/env python3
"""Finalize the audited E34 comparison without promoting development results."""
import argparse
from collections import Counter
from pathlib import Path

import heart_branch_training as T
import heart_decision_sampling as D

P, H, S = T.P, T.H, T.S


def finish(root):
    S.verify_files(root)
    assert not (root / 'decision.json').exists()
    plan = H.read_json(root / 'plan.json')
    coverage = H.read_json(root / 'coverage-decision.json')
    assert coverage['passed']
    rows, passes, pairs = {}, [], Counter()
    common = H.read_json(root / 'common-holdout-report.json')
    assert common['status'] == 'complete'
    assert common['labels_sha256'] == S.sha(root / 'common-holdout-labels.json')
    for arm in ('small', 'expanded'):
        dst = root / arm
        S.verify_files(dst)
        proof = H.read_json(dst / 'completion-verification.json')
        assert proof['status'] == 'complete'
        for name, expected in proof['hashes'].items():
            assert S.sha(dst / name) == expected
        report = H.read_json(dst / 'report.json')
        training = H.read_json(dst / 'training-report.json')
        collection = H.read_json(dst / 'collection-report.json')
        assert common['candidate_hashes'][arm] == training['checkpoint_sha256'] == S.sha(dst / 'candidate.pt')
        rows[arm] = {'candidate_sha256': training['checkpoint_sha256'], 'optimizer_updates': training['optimizer_updates'],
            'families': collection['families'], 'family_coverage': collection['family_coverage'],
            'states': collection['overall']['roots'], 'branches': collection['branches'],
            'development_heart_wins': report['candidate_wins'], 'baseline_heart_wins': report['baseline_wins'],
            'paired_against_baseline': report['paired'], 'development_gate_passed': report['development_gate_passed'],
            'common_holdout': common['models'][arm], 'report_sha256': S.sha(dst / 'report.json'),
            'verification_sha256': S.sha(dst / 'completion-verification.json')}
        if report['development_gate_passed']:
            passes.append(arm)
    seeds = H.read_json(root / 'seeds.json')['train_development']
    for seed in seeds:
        a, b = [H.read_json(root / arm / f'evaluation/{seed}.json.gz')['status'] == 'heart_win'
            for arm in ('small', 'expanded')]
        pairs['both_win' if a and b else 'small_only' if a else 'expanded_only' if b else 'both_fail'] += 1
    selected = sorted(passes, key=lambda a: (-rows[a]['development_heart_wins'],
        rows[a]['paired_against_baseline'].get('baseline_only', 0), a != 'expanded'))[0] if passes else None
    report = {'experiment': 'E34', 'status': 'complete', 'finished_at': P.utc(), 'models': rows,
        'paired_expanded_vs_small': dict(pairs), 'paired_exact_p': D.exact_p(pairs['small_only'], pairs['expanded_only']),
        'selected_for_fresh_acceptance': selected, 'promoted_deployed_policy': False,
        'new_acceptance_seeds': 0, 'source_report_sha256': S.sha(root / 'source-report.json'),
        'label_verification_sha256': S.sha(root / 'label-verification.json'),
        'common_holdout_report_sha256': S.sha(root / 'common-holdout-report.json'),
        'next_step': 'freeze selected arm and run the predeclared paired fresh acceptance' if selected else
            'both fixed-budget data arms failed the whole-game gate; preserve negative result and diagnose a distinct cause before another intervention',
        'limits': plan['limits']}
    H.write_json(root / 'decision.json', report)
    lines = ['# E34：扩大独立训练家庭的结果', '',
        '战斗运行时、网络结构、初始化权重、候选规则与 2,000 次训练更新相同。以下 1,024 局属于历史训练开发集，不能当作未见种子成绩。', '',
        '| 指标 | 小数据 | 扩展数据 |', '|---|---:|---:|']
    for label, values in [
            ('拟合家庭', [rows[a]['families']['fit'] for a in ('small', 'expanded')]),
            ('可救拟合家庭', [rows[a]['family_coverage']['fit']['rescued'] for a in ('small', 'expanded')]),
            ('混合标签拟合家庭', [rows[a]['family_coverage']['fit']['mixed'] for a in ('small', 'expanded')]),
            ('开发集心脏胜局', [rows[a]['development_heart_wins'] for a in ('small', 'expanded')]),
            ('原胜新败', [rows[a]['paired_against_baseline'].get('baseline_only', 0) for a in ('small', 'expanded')]),
            ('共同留出局面中获胜的选择', [rows[a]['common_holdout']['full_legal_choice_wins_among_labelled'] for a in ('small', 'expanded')]),
            ('开发门槛通过', [rows[a]['development_gate_passed'] for a in ('small', 'expanded')])]:
        lines.append(f'| {label} | {values[0]} | {values[1]} |')
    lines += ['', f'原策略为 {rows["small"]["baseline_heart_wins"]}/1,024。两候选逐种子对照：{dict(pairs)}，配对精确 p={report["paired_exact_p"]:.6g}。', '',
        f'进入新种子验收的候选：{selected or "无"}。部署策略未由本开发结果替换。', '',
        '全部自然源、干预和终局核验见 label-verification.json；两组整局核验见对应目录 completion-verification.json。故障不作失败标签；同一家族分支不算独立种子。原版 Java 一致性保持 INCOMPLETE。']
    (root / '数据规模结果.md').write_text('\n'.join(lines) + '\n')
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    finish(parser.parse_args().root.resolve())
