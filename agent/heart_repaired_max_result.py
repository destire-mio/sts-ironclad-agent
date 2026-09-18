#!/usr/bin/env python3
"""Package a repaired search profile after its frozen prospective audit passes."""
import argparse
import difflib
from pathlib import Path
import shutil
import subprocess
import tempfile

from heart_max_backup_result import read, sha, write, verify_manifest


def prepare_patch(root, build):
    protocol = read(root/'confirmation-protocol.json')
    bounded = bool(protocol.get('profile_validation'))
    if bounded:
        evidence_path = build/'build-report.json'
        evidence = read(evidence_path)
        assert evidence['experiment'] == 'E53' and evidence['mode'] == 'bounded'
        assert sha(Path(evidence['source_build_report'])) == evidence['source_build_report_sha256']
        parent_build = Path(evidence['source_build_report']).parent
        original, changed = parent_build/'inputs/ordered.cpp', build/'terminal_loss.cpp'
        assert evidence['source_sha256'] == sha(changed)
        parent_evidence = read(parent_build/'fixed-build-report.json')
        assert next(c for c in parent_evidence['compiles'] if c['kind']=='mean')['source_sha256'] == sha(original)
        engine_sha = evidence['candidate_engine_sha256']
    else:
        evidence_path = build/'fixed-build-report.json'
        evidence = read(evidence_path)
        original, changed = build/'inputs/ordered.cpp', build/'inputs/max_backup.cpp'
        assert next(c for c in evidence['compiles'] if c['kind']=='maximum')['source_sha256'] == sha(changed)
        engine_sha = evidence['engines']['maximum']['sha256']
    assert engine_sha == sha(root/'candidate/engine/slaythespire.cpython-312-darwin.so')
    name = 'src/sim/search/BattleScumSearcher2.cpp'
    patch = ''.join(difflib.unified_diff(original.read_text().splitlines(True), changed.read_text().splitlines(True),
        fromfile='a/'+name, tofile='b/'+name))
    output = root/('search-bounded-loss.patch' if bounded else 'search-max-backup.patch')
    assert not output.exists()
    output.write_text(patch)
    with tempfile.TemporaryDirectory(prefix='heart-repaired-max-source-') as directory:
        target = Path(directory)/name
        target.parent.mkdir(parents=True)
        shutil.copy2(original, target)
        subprocess.run(['git','apply','--check',str(output)], cwd=directory, check=True, capture_output=True)
        subprocess.run(['git','apply',str(output)], cwd=directory, check=True, capture_output=True)
        assert sha(target)==sha(changed)
    write(root/'portable-search-patch-verification.json', {'status':'complete',
        'patch_sha256':sha(output), 'before_source_sha256':sha(original), 'after_source_sha256':sha(changed),
        'patched_source_equals_compiled_candidate':True, 'build_report':str(evidence_path),
        'build_report_sha256':sha(evidence_path), 'patch_name':output.name,
        'candidate_engine_sha256':engine_sha,
        'prerequisites':['sim_patch/action_queue.patch','sim_patch/search_rollout.patch','sim_patch/search_order.patch'],
        'adoption':f"Source reproduction only. Completion verification and the frozen {protocol['experiment']} gate are required."})


def finalize(root):
    verify_manifest(root)
    report, proof, decision = (read(root/name) for name in ('report.json','completion-verification.json','decision.json'))
    protocol, plan = read(root/'confirmation-protocol.json'), read(root/'plan.json')
    experiment = protocol['experiment']
    bounded = bool(protocol.get('profile_validation'))
    assert experiment == ('E54' if bounded else 'E51')
    assert report['experiment']==decision['experiment']==plan['experiment']==experiment
    assert report['status']==proof['status']==decision['status']=='complete'
    for name, expected in proof['report_hashes'].items(): assert sha(root/name)==expected, name
    assert sha(root/'winning-route-verification.json')==proof['winning_routes_sha256']
    assert sha(root/'verify_completed_run.py')==proof['verification_script_sha256']
    for key,name in [('report_sha256','report.json'),('verification_sha256','completion-verification.json'),
                     ('protocol_sha256','confirmation-protocol.json')]:
        assert decision[key]==sha(root/name)
    validation = Path(protocol['repair_validation'])
    assert sha(validation/'completion-verification.json')==protocol['repair_verification_sha256']
    for name,expected in read(validation/'completion-verification.json')['evidence_hashes'].items():
        assert sha(Path(name))==expected,name
    if bounded:
        profile = Path(protocol['profile_validation'])
        profile_proof = read(profile/'completion-verification.json')
        assert sha(profile/'completion-verification.json') == protocol['profile_verification_sha256']
        assert profile_proof['status'] == 'complete' and profile_proof['probe_gate_passed'] and profile_proof['stress_gate_passed']
        for name, expected in profile_proof['evidence_hashes'].items():
            assert sha(Path(name)) == expected, name
        assert profile_proof['engines']['candidate'] == sha(root/'candidate/engine/slaythespire.cpython-312-darwin.so')
        for item in protocol['additional_failed_history']:
            assert sha(Path(item['path'])) == item['sha256']
    assert sha(Path(protocol['failed_E49_decision']))==protocol['failed_E49_decision_sha256']
    assert proof['fresh_seed_overlap']==0 and proof['winner_outside_nn_choices_verified']
    old,new=report['arms']['baseline'],report['arms']['candidate']
    for arm,data in [('baseline',old),('candidate',new)]:
        verify_manifest(root/arm)
        assert data['execution_faults']==0 and data['results']==data['assigned_seeds']==1024
        assert proof['arms'][arm]['episodes']==1024
        assert proof['arms'][arm]['heart_wins']==proof['arms'][arm]['winner_reruns']==data['heart_wins']
        assert sha(root/arm/'engine/slaythespire.cpython-312-darwin.so')==data['identity']['engine_sha256']
        assert sha(root/arm/'model.pt')==protocol['outside_model_sha256']
    assert proof['winner_boss_routes_verified']==old['heart_wins']+new['heart_wins']
    assert proof['paired']==report['paired']==decision['paired']
    accepted=new['heart_wins']-old['heart_wins']>=15 and report['paired_exact_p']<.01
    assert accepted==decision['confirmation_gate_passed']==decision['supported_as_next_combat_profile']
    assert decision['observed_ten_percent_target_met'] == report['observed_ten_percent_target_met'] == (new['heart_wins']>=103)
    patch=read(root/'portable-search-patch-verification.json')
    patch_name = 'search-bounded-loss.patch' if bounded else 'search-max-backup.patch'
    assert patch['patch_sha256']==sha(root/patch_name)
    assert patch['candidate_engine_sha256']==new['identity']['engine_sha256']
    assert sha(Path(patch['build_report']))==patch['build_report_sha256']
    selected=root/('candidate' if accepted else 'baseline')
    data=new if accepted else old
    selection={'status':'complete','experiment':experiment,'selected_runtime':str(selected),
        'selected_runtime_manifest_sha256':sha(selected/'manifest.json'),
        'selected_engine_sha256':data['identity']['engine_sha256'],
        'selected_model_sha256':data['identity']['model_sha256'],
        'maximum_backup_accepted':accepted,'outside_model_updated':False,
        'defeat_draw_turn_bonus_cap':20 if bounded and accepted else None,
        'queue_repair_included':True,'search_simulations_per_call':8000,'boss_multiplier':3,
        'selected_config_sha256':sha(selected/'config.json'),
        'decision_sha256':sha(root/'decision.json'),'verification_sha256':sha(root/'completion-verification.json'),
        'retired_acceptance_seeds':str(root/'seeds.json'),
        'next_training_requirement':'Freeze this complete runtime and regenerate training trajectories and continuation labels on assigned training families. Do not use E49/E51/E54 confirmation roots or mix labels from older game-rule/search versions.',
        'limits':'Simulator result. Existing outside NN is unchanged; full original-Java parity remains incomplete.',
        'selection_script_sha256':sha(Path(__file__))}
    assert not (root/'selected-runtime.json').exists()
    if accepted:
        target=root.parent.parent/('sim_patch/search_bounded_loss.patch' if bounded else 'sim_patch/search_max_backup.patch')
        assert not target.exists() or sha(target)==sha(root/patch_name)
        shutil.copy2(root/patch_name,target)
    write(root/'selected-runtime.json',selection)
    rows=[]
    candidate_title = '最大值搜索＋败局加分上限' if bounded else '修复后最大值搜索'
    for title,arm,data in [('修复后均值搜索','baseline',old),(candidate_title,'candidate',new)]:
        lo,hi=report['wilson_95_intervals'][arm]
        rows.append(f'| {title} | {data["heart_wins"]}/1,024 | {data["heart_wins"]/1024:.2%} | {lo:.2%}—{hi:.2%} | {data["search_simulations"]:,} |')
    pairs=report['paired']; cost=new['search_simulations']/old['search_simulations']-1
    extra_change = '败局推演的抽牌与回合加分之和限制为 20，避免极端败局分数反超胜局。上限之下保留数学公式，但表达式重组不保证浮点逐位一致。' if bounded else ''
    failed_history = 'E51 因 1 个超时失败，E52 删除全部败局加分损失 3 个旧胜局而失败；E53 设上限版本通过开发筛选和三个故障回归，然后用全新根进行本次确认。' if bounded else ''
    body=f'''# {experiment}：修复后战斗搜索的完整确认

采用门槛：{'通过，选用最大值搜索' if accepted else '未通过，选用修复后的均值搜索'}。观测 10% 目标：{'达到' if new['heart_wins']>=103 else '未达到'}。

两组使用同一批 1,024 个新根，排除 {plan['excluded_historical_or_reserved']:,} 个历史/预留根。范围为铁甲战士 A20，自然开局、三钥匙、第三幕双 Boss、第四幕矛盾与心脏，排除棱彩碎片。游戏规则共享 E50 队列修复；局外网络为原权重，每次搜索 8,000、Boss ×3，整局/进程保护 300/360 秒。

| 系统 | 心脏胜利 | 样本通关率 | 95% Wilson 区间 | 整局总搜索量 |
|---|---:|---:|---:|---:|
{chr(10).join(rows)}

共同胜 {pairs.get('both_win',0)}，新胜 {pairs.get('candidate_only',0)}，旧胜新败 {pairs.get('baseline_only',0)}，共同败 {pairs.get('both_fail',0)}；净增 {new['heart_wins']-old['heart_wins']} 胜，精确配对 p={report['paired_exact_p']:.8g}。整局搜索量变化 {cost:+.2%}，单次预算相同不代表整局开销相同；并发运行用时不作为速度提升证据。

变化位于战斗 MCTS：评估一条出牌分支时，用推演找到的最佳回报分配搜索机会，替代所有推演回报的均值。{extra_change}合法行动、随机推演、探索系数和局外网络相同。这个对照检验战斗搜索，不代表局外网络的新学习成果。

E45 的原保留门槛失败、E49 的队列溢出和超时失败判定保留。E50 修复容量和胜利结算队尾，两组共享修复后的规则。{failed_history}{experiment} 用另一批新种子检验净收益。在抽种子前固定净增至少 15 胜、配对 p<0.01 和完整核验要求；未按结果调参或补充本批分母。

执行故障/截断 0；2,048 个自然终局通过行动、状态及 RNG 重放；{proof['winner_boss_routes_verified']} 次胜局从开局重规划，行动和终态一致。每个胜局通过钥匙、双 Boss、矛盾、心脏及局外网络动作核验，每对种子的第一处行动变化通过相同状态/RNG 的战斗入口检查。源码增量补丁输出与编译输入一致。

后续训练使用[所选运行时](selected-runtime.json)，重算训练种子的自然轨迹和完整续局标签；旧标签保留引擎身份。本批确认根退出训练和未来的新种子验收。原版 Java 全链路对齐为 INCOMPLETE，本报告不代表原版胜率。样本通关率与总体胜率区间下限分开解释。

证据：[抽种子前协议](confirmation-protocol.json)、[报告](report.json)、[逐种子对照](paired-outcomes.json)、[核验](completion-verification.json)、[胜局路线](winning-route-verification.json)、[判定](decision.json)、[搜索补丁]({patch_name})、[源码核验](portable-search-patch-verification.json)。实验目录被 Git 忽略，交接需保留原生模块、模型、源码和轨迹。
'''
    (root/'验收结果.md').write_text(body)
    print({'accepted':accepted,'baseline_wins':old['heart_wins'],'candidate_wins':new['heart_wins'],
        'net':new['heart_wins']-old['heart_wins'],'paired_p':report['paired_exact_p'],
        'search_cost_change':cost,'selected_runtime':str(selected)},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare-patch','finalize'))
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--build',type=Path)
    args=parser.parse_args()
    if args.command=='prepare-patch': prepare_patch(args.root.resolve(),args.build.resolve())
    else: finalize(args.root.resolve())
