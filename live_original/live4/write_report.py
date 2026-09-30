"""Source-bound live4 report; pending attempts prevent a final acceptance claim."""
import argparse
import json
from pathlib import Path
from cli import W, H, summary

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--interim', action='store_true')
    a=ap.parse_args()
    summary(H/'teacher'); summary(W/'student')
    teacher=json.loads((H/'teacher/summary.json').read_text())
    student=json.loads((W/'student/summary.json').read_text())
    audit=json.loads((W/'evidence/audit.json').read_text())
    preflight=json.loads((W/'evidence/student-preflight.json').read_text())
    trows={r['seed']:r for r in teacher['rows']}
    if not a.interim:
        assert teacher['pending']==teacher['running']==student['pending']==student['running']==0
        assert not audit['errors'] and not audit['source_changes'] and not audit['owned_java']
        assert audit['attempts_audited']==132
    lines=[('live4 中间报告：验收未结束。' if a.interim else 'live4 固定种子验证结束。')+
           f"老师自然终局 {teacher['completed']}/100，胜 {teacher['wins']}，故障 {teacher['faults']}；"
           f"学生自然终局 {student['completed']}/32，胜 {student['wins']}，故障 {student['faults']}。",
           '', '老师配对使用 live3 保存的 c42-merge.jsonl 同种子快照。故障不计自然败局；胜负一致率使用双方有胜负的配对。', '',
           '| 指标 | 结果 |','|---|---:|',
           f"| 原版胜率（自然终局） | {teacher['wins']}/{teacher['completed']} = {teacher['original_rate']:.2%} |",
           f"| 胜负一致率 | {teacher['paired']['both_win']+teacher['paired']['both_loss']}/{teacher['paired_completed']} = {teacher['agreement']:.2%} |",
           f"| 双方胜／双方负 | {teacher['paired']['both_win']}／{teacher['paired']['both_loss']} |",
           f"| 原版独赢／模拟器独赢 | {teacher['paired']['original_only']}／{teacher['paired']['simulator_only']} |",
           f"| 无法继续（bridge fault） | {teacher['faults']}/{100-teacher['pending']-teacher['running']} 个结束尝试 |",'',
           ('100 个指定种子的尝试记录齐全，按观测故障率判断 ≤3% 门槛；该结果不证明所有游戏状态对齐。'
            if teacher['pending']==teacher['running']==0 else f"老师待跑 {teacher['pending']}，在途 {teacher['running']}；100 局与 ≤3% 门槛没有验收结论。"), '',
           '| 版本组 | 局数 | 胜／负／故障 | 胜负配对一致 |','|---|---:|---:|---:|']
    old_runtime=json.loads((W/'runtime-history.json').read_text())['parent']
    for g in audit['version_groups']:
        if g['policy']=='student':
            label='学生第一版，live3 历史组' if g['model_sha256'].startswith('7a316cfa') else '学生第二版，live4 修复包'
            agreement='无配对'
        else:
            label=('老师 live4 陀螺顺序修复' if g['runtime_sha256']!=old_runtime else
                   '老师 live3 形状怪导入修复' if min(g['seeds'])>=3900012012 else '老师 live3 初始导入器')
            paired=[trows[s] for s in g['seeds'] if trows[s]['complete'] and trows[s]['simulator_win'] is not None]
            agreement=str(sum((r['status']=='win')==r['simulator_win'] for r in paired))+'/'+str(len(paired))
        lines.append(f"| {label}（{min(g['seeds'])}–{max(g['seeds'])}） | {len(g['seeds'])} | {g['wins']}／{g['losses']}／{g['faults']} | {agreement} |")
    lines += ['', '学生口径：固定集合 3900016000–3900016031，旧 16 局使用第一版模型，第二版补未尝试的后 16 局。32 局是两版的桥接记录，不是第二版 32 局验收，不据此判断学生胜率。云端第二版开发评估的 1000 个种子为 3900040000–3900040999，与本组无交集，标为无配对。', '',
        '第二版冻结模型 SHA-256：`90b937349181b165a1d3281f03481e92e221c915869627ef6e9fa9e4e094fa2b`。载入核对模型 SHA、完整 schema 和编码器 SHA；eval 模式、参数冻结，老师／局外规则调用报错。第三版沿用同一 checkpoint/schema/接口时可换 `--model`，输出目录绑定模型，禁止改写既有批次。', '',
        f"保存原版状态的离线检查：{preflight['decisions']} 个局外状态、{preflight['candidates']} 个候选，六组输入和 11195 维特征与生产训练加载路径逐位一致，6 次禁止调用探针通过。整局特征检查累计 {student['student_feature_decisions']} 个决策、{student['student_feature_candidates']} 个候选（含两版历史组；逐局计数见 summary）。", '',
        '修复：老师 3900012007 的时间吞噬者战，最后一张手牌触发强制结束回合；原版刷新手牌后让陀螺抽 1 张，旧核心漏掉此步骤，引发抽牌数、牌堆和卡牌随机流差异。单步导入并执行保存动作可复现 30 处差异；修复后为 0，其他 50 个保存动作的比较结果保持，其中 9 个带有既有差异。验证没有新搜索或 Java 重开局。旧结果保留，后续整局使用派生运行包。', '',
        '局外 RNG 重置时点、界面表示和其他状态差异保留在轨迹中；0 bridge fault 与完整引擎等价是不同结论。老师独赢／独输只能说明结局分叉，不能用首个轨迹差异证明胜负原因。', '',
        f"审计覆盖 {audit['attempts_audited']} 个结束尝试；错误 {len(audit['errors'])}，源码清单变化 {len(audit['source_changes'])}。检查包括原版种子/A20/胜利标志、一次自然开局、禁止读档 RPC、重复搜索根、战斗预算、特征与模型绑定、实例清理。", '',
        '[运行手册](<repo>/live_original/README.md) · [审计证据](<repo>/live_original/live4/evidence/audit.json) · [修复对照](<repo>/live_original/live4/evidence/top-repair-verification.json)', '',
        '老师：`./run.sh --policy teacher`',
        '学生：`./run.sh --policy student --model <repo>/live_original/live4/models/distill2_frozen.pt`', '']
    target=H.parents[2]/'scratchpad/parity/live4-report.md'
    target.write_text('\n'.join(lines))
    print(target)

if __name__=='__main__':main()
