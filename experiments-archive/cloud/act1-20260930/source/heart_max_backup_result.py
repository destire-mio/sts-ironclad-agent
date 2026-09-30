#!/usr/bin/env python3
"""Package the completed E49 decision without changing its frozen experiment."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def verify_manifest(root):
    manifest = read(root / 'manifest.json')
    for name, expected in manifest['frozen_files'].items():
        assert sha(root / name) == expected, name
    return manifest


def prepare_patch(root, build):
    """Check source reproduction only; this does not select a runtime."""
    evidence = read(build / 'build-report.json')
    for name, expected in evidence['inputs'].items():
        assert sha(build / name) == expected, name
    assert evidence['candidate_sha256'] == sha(build / 'candidate/slaythespire.cpython-312-darwin.so')
    assert evidence['candidate_sha256'] == sha(root / 'candidate/engine/slaythespire.cpython-312-darwin.so')
    original, changed = build / 'inputs/ordered.cpp', build / 'inputs/max_backup.cpp'
    source_name = 'src/sim/search/BattleScumSearcher2.cpp'
    patch = ''.join(difflib.unified_diff(original.read_text().splitlines(True),
        changed.read_text().splitlines(True), fromfile='a/' + source_name, tofile='b/' + source_name))
    destination = root / 'search-max-backup.patch'
    if destination.exists():
        assert destination.read_text() == patch
    else:
        destination.write_text(patch)
    with tempfile.TemporaryDirectory(prefix='heart-max-patch-') as folder:
        target = Path(folder) / source_name
        target.parent.mkdir(parents=True)
        shutil.copy2(original, target)
        for check in (True, False):
            command = ['git', 'apply'] + (['--check'] if check else []) + [str(destination)]
            subprocess.run(command, cwd=folder, check=True, capture_output=True, text=True)
        assert target.read_bytes() == changed.read_bytes()
    proof = {'status': 'complete', 'portable_patch_sha256': sha(destination),
        'applies_after': 'sim_patch/search_order.patch',
        'before_source_sha256': sha(original), 'compiled_source_sha256': sha(changed),
        'patched_source_equals_compiled_candidate': True,
        'build_report': str(build / 'build-report.json'),
        'build_report_sha256': sha(build / 'build-report.json'),
        'candidate_engine_sha256': evidence['candidate_sha256'],
        'default_simulator_source_modified': False,
        'adoption': 'Source reproduction only; E49 completed confirmation is required for selection.'}
    write(root / 'portable-patch-verification.json', proof)
    print({'status': 'source_patch_verified', 'engine': evidence['candidate_sha256']}, flush=True)


def finalize(root):
    verify_manifest(root)
    report, proof = read(root / 'report.json'), read(root / 'completion-verification.json')
    decision, protocol = read(root / 'decision.json'), read(root / 'confirmation-protocol.json')
    plan = read(root / 'plan.json')
    assert report['status'] == proof['status'] == decision['status'] == 'complete'
    assert report['experiment'] == decision['experiment'] == protocol['experiment'] == 'E49'
    for name, expected in proof['report_hashes'].items():
        assert sha(root / name) == expected, name
    assert proof['winning_routes_sha256'] == sha(root / 'winning-route-verification.json')
    assert proof['verification_script_sha256'] == sha(root / 'verify_completed_run.py')
    assert decision['report_sha256'] == sha(root / 'report.json')
    assert decision['verification_sha256'] == sha(root / 'completion-verification.json')
    assert decision['protocol_sha256'] == plan['confirmation_protocol_sha256'] == sha(root / 'confirmation-protocol.json')
    historical = Path(protocol['historical_decision_unchanged'])
    assert sha(historical) == protocol['historical_decision_sha256']
    assert read(historical)['development_gate_passed'] is False
    assert proof['fresh_seed_overlap'] == 0 and proof['winner_outside_nn_choices_verified']
    n = protocol['required_pairs']
    assert report['seeds'] == n == 1024
    old, new = report['arms']['baseline'], report['arms']['candidate']
    for name, arm in [('baseline', old), ('candidate', new)]:
        verify_manifest(root / name)
        assert arm['execution_faults'] == 0 and arm['results'] == arm['assigned_seeds'] == n
        assert proof['arms'][name]['episodes'] == n
        assert proof['arms'][name]['heart_wins'] == proof['arms'][name]['winner_reruns'] == arm['heart_wins']
        assert arm['identity']['engine_sha256'] == sha(root / name / 'engine/slaythespire.cpython-312-darwin.so')
        assert arm['identity']['model_sha256'] == sha(root / name / 'model.pt') == protocol['outside_model_sha256']
    assert proof['winner_boss_routes_verified'] == old['heart_wins'] + new['heart_wins']
    assert decision['paired'] == report['paired'] == proof['paired']
    accepted = (new['heart_wins'] - old['heart_wins'] >= protocol['minimum_net_additional_wins']
        and report['paired_exact_p'] < protocol['paired_two_sided_exact_p_less_than'])
    assert decision['confirmation_gate_passed'] == decision['supported_as_next_combat_profile'] == accepted
    assert decision['observed_ten_percent_target_met'] == (new['heart_wins'] >= 103)
    patch_proof = read(root / 'portable-patch-verification.json')
    assert patch_proof['patched_source_equals_compiled_candidate']
    assert patch_proof['portable_patch_sha256'] == sha(root / 'search-max-backup.patch')
    assert patch_proof['candidate_engine_sha256'] == new['identity']['engine_sha256']
    assert patch_proof['build_report_sha256'] == sha(Path(patch_proof['build_report']))
    previous = root.parent / 'heart-binding-validation-20260917-01/decision.json'
    prior = read(previous)
    selected = root / 'candidate' if accepted else Path(prior['selected_runtime'])
    chosen = new if accepted else old
    result = {'status': 'complete', 'experiment': 'E49',
        'supported_as_next_training_combat_baseline': accepted,
        'selected_runtime': str(selected), 'selected_runtime_manifest_sha256': sha(selected / 'manifest.json'),
        'selected_engine_sha256': chosen['identity']['engine_sha256'],
        'selected_model_sha256': chosen['identity']['model_sha256'],
        'outside_model_updated': False, 'original_default_engine_overwritten': False,
        'search_policy_updated': accepted, 'search_budget_updated': False,
        'target_observed_ten_percent_met': decision['observed_ten_percent_target_met'],
        'selection_rule': protocol['decision'], 'historical_E45_gate_remains_failed': True,
        'decision_sha256': sha(root / 'decision.json'),
        'verification_sha256': sha(root / 'completion-verification.json'),
        'previous_decision_sha256': sha(previous),
        'incremental_patch_sha256': sha(root / 'search-max-backup.patch'),
        'patch_prerequisite': 'sim_patch/search_order.patch',
        'training_evidence': plan['source'],
        'retired_acceptance_seeds': str(root / 'seeds.json'),
        'retirement': 'Never use these roots for training or as a new acceptance pool.',
        'next_training_requirement': 'Freeze this selected combat runtime and the outside continuation. Regenerate natural training trajectories and branch outcomes on assigned training roots; older E32 labels retain their engine identity. Do not train on E49 confirmation roots. No reuse of rejected NN weights.',
        'limits': protocol['limits'], 'selection_script_sha256': sha(Path(__file__))}
    output = root / 'selected-runtime.json'
    assert not output.exists(), 'preserve the existing selection'
    if accepted:
        destination = root.parent.parent / 'sim_patch/search_max_backup.patch'
        if destination.exists():
            assert sha(destination) == sha(root / 'search-max-backup.patch')
        else:
            shutil.copy2(root / 'search-max-backup.patch', destination)
    write(output, result)
    paired = report['paired']
    cost = new['search_simulations'] / old['search_simulations'] - 1
    table = []
    for title, name, arm in [('旧版均值搜索', 'baseline', old), ('候选最大值搜索', 'candidate', new)]:
        low, high = report['wilson_95_intervals'][name]
        table.append(f'| {title} | {arm["heart_wins"]}/{n:,} | {arm["heart_wins"]/n:.2%} | {low:.2%}—{high:.2%} | {arm["search_simulations"]:,} |')
    stage_table = []
    for act in (2, 3, 4):
        counts = [sum(v for k, v in arm['terminal_distribution'].items() if int(k.split(':')[0]) >= act) for arm in (old, new)]
        stage_table.append(f'| 到达第 {act} 幕 | {counts[0]} | {counts[1]} |')
    body = f'''# E49：战士 A20 心脏最大值搜索确认

范围为模拟器自然开局、三把钥匙、第三幕两个不同 Boss、第四幕矛盾和心脏，排除棱彩碎片。两组各使用同一批 {n:,} 个新根种子，与 {plan['excluded_historical_or_reserved']:,} 个历史及预留种子无重合。局外网络为原权重，搜索预算为每次 8,000、Boss ×3。

| 系统 | 心脏胜利 | 通关率 | 95% Wilson 区间 | 整局总搜索量 |
|---|---:|---:|---:|---:|
{chr(10).join(table)}

共同胜利 {paired.get('both_win', 0)}，新增胜利 {paired.get('candidate_only', 0)}，旧胜新败 {paired.get('baseline_only', 0)}，共同失败 {paired.get('both_fail', 0)}；净增 {new['heart_wins']-old['heart_wins']} 个胜局，精确配对检验 p={report['paired_exact_p']:.8g}。整局搜索量变化 {cost:+.2%}，每次预算相同不代表整局成本相同。两组并发执行，运行耗时不作为速度提升证据。

| 路线进度 | 旧版 | 候选 |
|---|---:|---:|
{chr(10).join(stage_table)}

改动发生在战斗 MCTS：每个节点记录找到过的最佳终局回报，搜索分配使用这个值，替代原先的平均回报。全合法行动树、随机推演、探索系数、局外权重与每次搜索预算相同。这是战斗搜索收益，不能算作局外神经网络学习收益。

E45 开发集为 81 对 48，新增 51、丢失 18，未通过原“最多丢失 10 个旧胜局”的门槛；该失败判定保留。E49 为另一项前瞻确认：在抽取这批新种子前，登记“净增至少 15 胜、精确配对 p<0.01、全部核验通过”的规则。没有将 E45 的旧门槛写成通过，也没有根据 E49 结果调参或扩充本批种子。

E49 准入判断：{'通过，选用候选作为后续训练的战斗运行时' if accepted else '未通过，保留 E32 战斗运行时'}。观测 10% 目标：{'通过' if decision['observed_ten_percent_target_met'] else '未达到'}，该分母需要至少 103 个胜局。样本比例与总体胜率的置信下限为不同指标。

执行故障 0；两组 {2*n:,} 个自然终局通过动作、状态和 RNG 重放。{proof['winner_boss_routes_verified']} 次胜局从开局重跑网络与 MCTS 后行动与终态一致，路线核验包括三钥匙、第三幕双 Boss、矛盾与心脏，以及胜局中的局外网络决策。源码补丁在隔离副本应用后与候选编译输入逐字节相同。

本批新种子退出训练和未来新种子验收。下一轮训练使用所选战斗器重算自然轨迹和续局标签，旧 E32 标签保留版本身份。原版 Java 全链路对齐状态为 INCOMPLETE，这些结果不构成原版游戏胜率证据。

证据：[抽种子前规则](confirmation-protocol.json)、[完整报告](report.json)、[逐种子对照](paired-outcomes.json)、[核验记录](completion-verification.json)、[胜局路线](winning-route-verification.json)、[确认判定](decision.json)、[所选运行时](selected-runtime.json)、[增量补丁](search-max-backup.patch)、[补丁核验](portable-patch-verification.json)。`runs/` 被 Git 忽略；交接需保留权重、原生模块、源码和轨迹。
'''
    (root / '验收结果.md').write_text(body)
    print({'accepted': accepted, 'baseline_wins': old['heart_wins'], 'candidate_wins': new['heart_wins'],
        'paired': paired, 'p': report['paired_exact_p'], 'cost_change': cost,
        'ten_percent_met': decision['observed_ten_percent_target_met'], 'selected_runtime': str(selected)}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare-patch', 'finalize'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--build', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare-patch':
        prepare_patch(args.root.resolve(), args.build.resolve())
    else:
        finalize(args.root.resolve())
