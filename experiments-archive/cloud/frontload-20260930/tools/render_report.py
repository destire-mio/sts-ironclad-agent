"""Render the complete evidence; a positive first-stage result still needs an explicit adoption decision."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LOCAL='<repo-parent>/scratchpad/frontload-20260930'

def main():
    w=json.loads((ROOT/'evidence/whole-summary.json').read_text())
    m=json.loads((ROOT/'evidence/mechanism-summary.json').read_text())
    aligned=json.loads((ROOT/'evidence/aligned-battles.json').read_text())
    integrity=json.loads((ROOT/'evidence/preservation-final.json').read_text())
    p=w['pairs'];cpu=w['cpu'];f=m['all_act1_nonboss_fatal'];c=m['random_act1_nonboss_win']
    def pct(x):return f'{100*x:+.3f}%'
    def pp(x):return f'{100*x:+.3f} 个百分点'
    def interval(xs,format):return f'[{format(xs[0])}, {format(xs[1])}]'
    def link(name,label):return f'[{label}]({LOCAL}/{name})'
    if p['ci95'][0] <= 0:
        conclusion='不并入老师。整局胜率差的 95% 区间包含零或落在零以下，证据未达到预设并入门槛。'
        followup='flall 与额外 1000 局复核不启动，原因是 fl1 未达到胜率门槛。'
    elif not w['adopt']:
        conclusion='不并入老师。fl1 的胜率差达到首轮区间门槛，CPU 或完整性验收未达到预设要求，原因见下文。'
        followup='本次证据支持保留 fl1 候选。flall 与额外 1000 局复核不启动，先处理当前验收缺口。'
    else:
        conclusion='fl1 达到首轮胜率与 CPU 门槛；扩展复核和并入决定待评估。此文件不是老师版本的启用声明。'
        followup='首轮结果达到扩展条件；需要结合复用种子边界决定后续验证范围。'
    table=['| 范围 | 基线均值 | frontload 均值 | 基线 p99 | frontload p99 | frontload 最大值 |',
           '|---|---:|---:|---:|---:|---:|']
    for title,b,n in [('整局 CPU 秒',cpu['base'],cpu['frontload']),
        ('单场 CPU 秒',w['base_battle_cpu'],w['frontload_battle_cpu']),
        ('第一幕非 Boss 单场 CPU 秒',w['base_act1_nonboss_cpu'],w['frontload_act1_nonboss_cpu']),
        ('单场墙钟秒',w['base_battle_wall'],w['frontload_battle_wall']),
        ('第一幕非 Boss 单场墙钟秒',w['base_act1_nonboss_wall'],w['frontload_act1_nonboss_wall'])]:
        table.append(f'| {title} | {b["mean"]:.3f} | {n["mean"]:.3f} | {b["p99"]:.3f} | {n["p99"]:.3f} | {n["maximum"]:.3f} |')
    detail=['| 整局 CPU 分布 | 均值 | 中位数 | p90 | p95 | p99 | 最大值 |','|---|---:|---:|---:|---:|---:|---:|']
    for label,d in [('基线',cpu['base']),('frontload',cpu['frontload'])]:
        detail.append('| '+label+' | '+' | '.join(f'{d[k]:.3f}' for k in ['mean','median','p90','p95','p99','maximum'])+' |')
    text=f'''# frontload 整局验证报告

{conclusion}

固定种子 3900012000–3900013999 共 2000 局：c42 基线 {p['base_wins']}/2000，fl1 {p['new_wins']}/2000；救回 {p['saved']} 局、被损 {p['lost']} 局、净变化 {p['net']:+d} 局。胜率差 {pp(p['difference'])}，pair.py 的 95% 区间为 {interval(p['ci95'],pp)}。每局平均 CPU {cpu['base']['mean']:.3f}→{cpu['frontload']['mean']:.3f} 秒，变化 {pct(cpu['ratio']-1)}，比值变化的 95% 区间为 {interval([x-1 for x in cpu['ratio_ci95']],pct)}。

**实现与边界**

候选保留 combat4r 的第一次 N 搜索与失败后的第二次 N 搜索。累计 2N 后没有存活终局时，在同一棵树和同一随机数流上追加 2N，然后行动。后续预算规则沿用基线。`fl1` 覆盖第一幕非 Boss；`flall` 覆盖第一至三幕非 Boss。Boss、盾矛、心脏排除。

源码副本在本工作目录，云端包为 `~/sts/runs/frontload-20260930/runtime-frontload`；Linux ARM 沿用正式 combat4r 的 core archive 和引擎二进制，重建 fightsim 绑定。版本标识 `frontload-20260930-v1`。驱动从 v21 复制为 v25，使用 `P300_RUNTIME` 选择新包。{link('evidence/frontload.patch','源码与驱动差异')}，{link('evidence/cloud-verification/runtime-frontload/frontload-build.json','构建命令与二进制身份')}。

单场硬上限为 172 万次访问，来自机制基线样本最大值 86 万的两倍。这个分母是样本最大值，并非每个新初始状态的反事实基线访问量；因此实现不提供“每个状态都小于实际基线两倍”的通用保证。达到上限后停止扩展并执行现存终局计划，没有终局计划则报错。机制样本中超过对应基线实际两倍的数量为 0；整局可比初始状态中该数量为 {len(aligned['over_actual_baseline_2x'])}，最大比值为 {aligned['max_actual_baseline_ratio']:.4f}。分叉后的状态没有额外运行反事实基线，不进入这个比例的分母。

**机制验收**

traj-c42/traj-c43 共 3000 局，清点第一幕 28317 场战斗。纳入全部 274 场非 Boss 致死战斗，并从 25231 场原胜战斗以固定随机种子 20260930 抽取 512 场。样本在候选搜索前冻结，没有按候选结果删选。

| 样本 | 数量 | 救回 | 被损 | 动作改变 | 基线 CPU 合计 | frontload CPU 合计 |
|---|---:|---:|---:|---:|---:|---:|
| 全部第一幕非 Boss 致死战斗 | {f['n']} | {f['saved']} | {f['lost']} | {f['actions_changed']} | {f['base_cpu']['mean']*f['n']:.3f} 秒 | {f['frontload_cpu']['mean']*f['n']:.3f} 秒 |
| 随机原胜对照 | {c['n']} | {c['saved']} | {c['lost']} | {c['actions_changed']} | {c['base_cpu']['mean']*c['n']:.3f} 秒 | {c['frontload_cpu']['mean']*c['n']:.3f} 秒 |

致死组 CPU 变化 {pct(f['cpu_relative_change'])}，原胜组 {pct(c['cpu_relative_change'])}。786 次基线搜索复现历史动作和战后状态；基线与候选共 1572 条计划通过合法动作、战后状态与 RNG 重放。7 个范围排除场景与 2 个访问量截断场景通过。{link('evidence/mechanism-summary.json','机制统计')}，{link('evidence/cloud-verification/evidence/scope-checks.json','范围及截断证据')}。

死亡组的 22 次战斗救回不等于 22 次整局救回，整局统计来自下面的固定 2000 种子结果。

**整局结果与 CPU**

基线和候选各运行一次完整对局，基线用于 CPU 测量与历史复现检查，胜负基准保留冻结的 c42-merge.jsonl。计时基线调用新运行包保留的 `resolve_combat4r`，候选调用 `resolve_frontload`，共享同一 core、编译条件与计时环境；计时基线与 c42 的完整动作轨迹逐局比较。机制阶段的基线搜索使用正式 combat4r 二进制。执行顺序按种子奇偶交替；首段每 100 个种子一批，后段使用固定 24 个工作进程和 100 个任务的滚动队列。pair.py 以种子为配对单位；补充 20000 次种子级 bootstrap，胜率差区间为 {interval(w['win_bootstrap_ci95'],pp)}。配对二项检验的双侧 p 值为 {p['exact_paired_binomial_p_two_sided']:.6g}，用于提醒少量分歧样本时正态区间的限制。{link('evidence/pair.txt','pair.py 原始输出')}，{link('evidence/whole-summary.json','整局统计与完整分布')}。

{chr(10).join(table)}

{chr(10).join(detail)}

每局平均 CPU 差 {cpu['mean_difference']:+.3f} 秒，95% 区间 {interval(cpu['mean_difference_ci95'],lambda x:f'{x:+.3f} 秒')}。CPU 验收预设为比值区间上界不超过 +5%，且平均差区间下界不大于零；本次 CPU 验收结果：{'通过' if cpu['ratio_ci95'][1]<=1.05 and cpu['mean_difference_ci95'][0]<=0 else '未通过'}。整局 CPU 变化包含救回后新增楼层与战斗的计算成本。

蒸馏评估提前启动，与 c49 对局并行时，frontload 的 CPU affinity 收窄到 1–2 核；外部配置占用达到 66 核时，frontload 工作进程暂停，内存中的搜索树和对局状态保留，资源释放后续算。其他时段按资源余量分配，最高 24 核，nice 15。墙钟耗时包含这些等待，不能当作算法 CPU 成本。整局 CPU 计时覆盖决策和战斗搜索，模型首次加载、轨迹写盘及对照核验在计时范围之外。{link('whole/resource-ledger.jsonl','资源记录')}，{link('whole/resource-pauses.jsonl','本任务暂停与恢复记录')}。

候选第一幕非 Boss 战斗 {w['eligible_battles']} 场，触发预算前移 {w['triggered_battles']} 场，触顶 {w['cap_hits']} 场。执行错误 {len(w['execution_errors'])}，历史基线漂移 {len(w['baseline_drift'])}，超硬上限 {len(w['capped_visit_violation'])}，范围排除违规 {len(w['excluded_trigger_violation'])}。{link('evidence/aligned-battles.json','同初始状态预算对照')}。

首批 100 对完成后，调度器在完整批次边界切换为固定 24 进程池，CPU affinity 按资源余量变化。切换解决低资源时创建的单进程池无法使用后续空闲核的问题。原控制器和子进程退出后，新控制器核对 200 条完成记录与开始标记，复用冻结的整局函数，从未开始的种子接续。算法、种子、每个种子的两臂顺序和计时口径保持原配置。最终开始标记 {integrity['started_arms']} 条、完成记录 {integrity['completed_arms']} 条，首批结果哈希变化数 {len(integrity['prior_completed_rows_changed'])}。{link('evidence/controller-continuation.json','批次接续证据')}。完成 {integrity['rolling_boundary_completed_pairs']} 对后，调度器在完成边界改为滚动队列，避免长局阻塞其他空闲进程。第二次接续前后记录哈希变化数 {len(integrity['rolling_boundary_rows_changed'])}，冻结的整局函数和每种子搜索次数保持原配置。{link('evidence/controller-continuous.json','滚动队列接续证据')}。完整动作轨迹在 `whole/traj-base` 与 `whole/traj-fl1`，云端对应目录为 `~/sts/runs/frontload-20260930/whole/`。

**决定与证据限制**

{followup}

本次 2000 种子复用 c42，是开发期整局配对证据。3900018000–3900018999 已用于 c39/c43，并参与本次机制筛查，不能称为未见种子。评估块 3900040000–3900041999 和锁定验收块没有用于本候选的搜索或统计。

正式云运行包变化数 {len(integrity['formal_runtime_changed'])}，受保护 v21/v22/v24 变化数 {len(integrity['protected_drivers_changed'])}，冻结输入变化数 {len(integrity['frozen_changed'])}。第一次整局预检发现清单缺 `frozen_files` 包装层，修复前没有整局搜索；该日志与旧清单保留。范围检查的第一版末尾枚举断言写错为 CORRUPT_HEART，修正为 THE_HEART 后检查通过。这两项属于打包与验收脚本问题，不进入胜负分母。

候选调用示例（试验入口，不代表并入老师）：

```python
result = fightsim.resolve_frontload(game, 40000, 12.0, "fl1", 1720000)
```

正式运行包保留原版本；本报告不分配老师 fix 版本号。
'''
    (ROOT/'report.md').write_text(text)
    print(ROOT/'report.md')

if __name__=='__main__':main()
