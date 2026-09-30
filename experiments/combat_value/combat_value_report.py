"""Write the Chinese study report from complete, hash-bound result ledgers."""
import hashlib
import json
import statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
S=ROOT/'runs/combat-valuenet-20260927'
def read(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def link(label,p): return f'[{label}]({Path(p).resolve()})'
def pp(x): return f'{100*x:+.2f}'
def interval(x,percent=False):
    scale=100 if percent else 1
    return f'[{x[0]*scale:+.2f}, {x[1]*scale:+.2f}]'


def main():
    status=read(S/'pipeline-status.json')
    assert status['phase']=='single_fight_complete',status
    training=read(S/'model/training.json');noise=read(S/'model/label-noise.json')
    roots=read(S/'roots.json');modes=[]
    for mode in ('prior','rollout'):
        p=S/f'evaluation/test-{mode}.summary.json'
        if p.exists():
            row=read(p);assert row['source_sha256']==sha(p.with_name(f'test-{mode}.jsonl'))
            assert row['model_sha256']==sha(S/'model/value.json');modes.append(row)
    closed=status['status']=='closed_no_gain'
    conclusion=('两轮单场验收没有达到采用门槛，关闭这两种候选，维持 `reuse`。整局实验为 **0 局**，预留的 5000000000 种子段没有消耗。'
        if closed else '单场门槛通过，整局验收待完成；单场结果不能换算为整局心脏胜率。')
    lines=['# 局内学习价值实验（2026-09-27）','',conclusion,'',
        '## 改动与边界','',
        '`codex/combat-valuenet-20260927` 从 `codex/heart-principles-20260924` 的 `8f9d33ee83c23fb2c9989d0e2a090fd1e55eafe1` 建立。主工作树文件没有作为写入目标；本轮没有 Git 提交或推送。支持文件、arena 核心和数据均以文件副本导入，读取前后核对 SHA256。',
        '',link('导入来源',S/'import-provenance.json')+' · '+link('轨迹来源',S/'episode-imports.json')+' · '+link('三模块同核构建',S/'runtime/value-build.json'),'',
        '`valuenet` 是可选 arm。保留复用子树和原有终局见证：搜索器仍需找到并执行通向终局的动作序列。神经网络只改变探索或 rollout 决策，预测值不会写入终局缓存，不会被报告为胜利。默认 `P300_ENGINE=arena` 和原有 arm 路径保持原行为。','',
        '| 轮次 | 候选 | 预先固定的做法 |','| --- | --- | --- |',
        '| 1 | prior | UCT 加 `2*(V-0.5)/sqrt(1+n/32)`；原有终局 rollout 保留。 |',
        '| 2 | rollout | rollout 前两次决策各有 50% 概率按所有合法动作的后状态价值择优；其余沿用原采样。 |','',
        '两轮使用同一个冻结模型，`V=0.8*p(win)+0.2*E(HP/maxHP)`，没有参数扫描。新模式限第二幕 Boss、第三幕楼层不低于 50 的双 Boss、心脏；普通战、第一幕和盾矛走 `reuse`。模型未在这些非目标战斗上接受训练。','',
        '模型为 512→32 ReLU→2 sigmoid。512 个输入包括玩家 HP/格挡/能量/力量/状态、回合和部分遗物计数、五个怪物槽的 HP/阶段/意图、四个牌堆的哈希牌特征。特征提取和推理由 C++ 执行，不在搜索路径调用 Python 或 Torch。输入不含种子数值；牌堆顺序、RNG 内部状态和部分规则细节未编码。哈希碰撞与信息缺失构成模型误差来源。','',
        '## 数据与标签','',
        '入口来自冻结 D1/D4/D5 文件引用的 281 条 P211 自然轨迹，恢复轨迹内实际到达的晚期 Boss。没有改牌、改 HP、换战斗或重设游戏 RNG。每个原始游戏种子／关卡／Boss 序号按哈希选一个入口；恢复入口后核对历史指纹。',
        '', '| 分组 | 种子家族 | 战斗入口 | 局内标签 |','| --- | ---: | ---: | ---: |']
    for split in ('train','valid','test'):
        group=[r for r in roots if r['split']==split]
        n=training['metrics'][split]['rows'] if split!='test' else '0（不拟合测试标签）'
        lines.append(f'| {split} | {len({r["family"] for r in group})} | {len(group)} | {n} |')
    lines+=['',
        '家族键是原始游戏种子。同种子的不同策略重复、训练轮次、Boss、搜索分支及 RNG 变体归入同一组。SHA256 固定分配约 60%/15%/25%，训练、验证、测试家族交集为空。历史局外父策略接触过这些轨迹，所以本轮是“新价值模型的家族隔离测试”，不是全系统从未见过种子的确认。','',
        '每个入口生成 12 条真实可执行路径，一半取小预算搜索找到的路径，一半取原有随机 rollout；在路径前半段抽取最多 8 个中间状态。每个状态用独立搜索随机流执行 256 次模拟，回放搜索找到的最佳终局，标签为胜负和 `胜利×终局HP/maxHP`。标签 HP 取战斗终局；验收 HP 取退出战斗后的游戏 HP，包含战后遗物效果，死亡／逃跑按 0。','',
        '训练抽样偏向路径前半段，验收搜索会访问更深的分支，两者的局面分布可能不同。本轮没有对深层状态单独校准，也没有用测试结果回调模型。','',
        '标签噪声来自有限预算漏掉胜路、随机动作采样、特征缺失和同一轨迹内相关性。256 次模拟的标签衡量有限搜索的可解性，不是最优价值，也不是整局通关概率。训练按家族等权采样；验证按家族等权选择预先固定的 40 个 epoch 中损失最低的一个。',
        '',f'同一个入口状态的 12 次独立搜索中，训练组有 {noise["train"]["roots_with_both_win_and_loss_labels"]}/{noise["train"]["roots"]} 个入口同时出现胜／负标签，验证组为 {noise["valid"]["roots_with_both_win_and_loss_labels"]}/{noise["valid"]["roots"]}。这是有限搜索标签波动的直接观测，不能解释为这些入口的真实最优胜率。'+link('标签噪声明细',S/'model/label-noise.json'),
        '',f'模型选择 epoch {training["selected_epoch"]}。模型 SHA256：`{training["model_sha256"]}`。',
        '', '| 分组 | 胜负 Brier | 常数预测 Brier | HP MSE | C++/Torch 最大绝对差 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for split,metric in training['metrics'].items():
        lines.append(f'| {split} | {metric["brier"]:.4f} | {metric["constant_brier"]:.4f} | {metric["hp_mse"]:.4f} | {metric["cpp_torch_max_abs"]:.2g} |')
    lines+=['', '拟合指标按家族加权，常数预测取训练组的加权标签均值，验证组沿用这个常数。这张拟合表不属于胜率证据。'+link('训练记录',S/'model/training.json')+' · '+link('预先固定的方案',S/'protocol.json')+' · '+link('执行与基线补充约束',S/'execution-plan.json'),'',
        '## 单场验收方法','',
        '测试有 88 个入口、30 个家族：第二幕 Boss 30 场，第三幕双 Boss 43 场，心脏 15 场。每个入口、每个候选重复两次。配对和置信区间按原始种子家族聚类，不能把重复次数或两场第三幕 Boss 当成独立家族。','',
        '先在独立进程运行交付的 PGO arena `reuse`，每步 32000、Boss ×12，记录完整战斗墙钟耗时。候选获得该入口相同的总时间上限，每轮搜索分配参考总耗时／参考搜索轮数。另一条对照使用候选同核的 `reuse`，也按相同时间上限运行。每一对串行交替顺序，第二遍反转入口顺序；跨入口最多 3 个工作进程，nice=10。','',
        '到期后完成当前 16 次模拟的原子批次，然后执行已有终局见证。结束战斗早于上限时不补时间。模型推理纳入计时；入口恢复、权重加载与独立回放排除。PGO 参考计时还包含战斗初始化及 Python 返回开销，候选的 C++ 内部计时排除初始化，差额属于方法限制。原始记录保留实际墙钟、进程 CPU 和负载。','',
        '本轮三个模块采用同一核心、O3 和 FullLTO 构建，没有重新训练 PGO。候选与同核计时对照的差异检验搜索设计；对原 PGO 包的比较检验交付替换价值。两类结果分表呈现，不把新构建速度变化归因于价值模型。','',
        '机器在 14:21 重启，中断第一轮验收。54 个完整配对保留，缺失任务在相同代码、模型和运行包身份下续跑；中断中的未落盘动作不构成输局。每个配对的两个臂仍在同一进程内串行执行；跨重启的外部负载变化是墙钟实验的环境限制。'+link('重启与恢复记录',S/'host-restart-20260927.json'),'',
        '原 PGO 运行包的校准完成于重启前，没有在每个候选旁重新执行一次。原 PGO 表用于固定生产模拟预算的参考；主要等墙钟结论依据同核串行配对。校准时段和验收时段的 CPU 竞争不同，不能用两个运行包的总耗时差推导模型加速倍数。','',
        '采用门槛：胜率差至少 +3 个百分点，针对两轮候选校正后的 97.5% 家族 bootstrap 区间下界大于 0；各关卡胜率差非负；总体 HP 差非负；计时对照的中位耗时比不高于 1.03、P95 不高于 1.10。候选还必须胜过原 PGO arena 固定预算结果。公开表给出 95% 区间，判定记录保留 97.5% 区间。20,000 次重采样使用固定随机种子。','',
        '区间描述这些历史可达入口上的配对差异，不能外推自然整局胜率。全体配对相同时 bootstrap 区间会退化为 0，不能据此排除小幅真实差异。心脏只有 15 个家族，检出小幅改进的能力有限。','',
        '## 原 PGO arena 固定模拟预算参考','',
        '基线每个入口运行一次；候选运行两次。表中的比率和均值按入口／重复计算，置信区间保留家族相关性。HP 将失败记为 0，避免只看幸存者。','',
        '| 候选 | 关卡 | 入口数 | 基线胜率 | 候选胜率 | 差值（百分点）及 95% CI | HP 差及 95% CI |',
        '| --- | --- | ---: | ---: | ---: | --- | --- |']
    for mode in modes:
        for stage in ('act2boss','act3boss','heart','all'):
            t=mode['fixed_reuse_statistics'][stage]
            lines.append(f'| {mode["mode"]} | {stage} | {t["roots"]} | {t["reuse_rate"]:.2%} | {t["candidate_rate"]:.2%} | {pp(t["win_difference"])} {interval(t["win_ci95"],True)} | {t["hp_difference"]:+.2f} {interval(t["hp_ci95"])} |')
    lines+=['','## 同核等时间配对与停止判断','',
        '| 候选 | 对照胜次／176 | 候选胜次／176 | 胜率差及 95% CI（百分点） | HP 差及 95% CI | 中位耗时比 / P95 | 采用 |',
        '| --- | ---: | ---: | --- | --- | --- | --- |']
    for mode in modes:
        t=mode['statistics']['all']
        lines.append(f'| {mode["mode"]} | {t["reuse_wins"]} | {t["candidate_wins"]} | {pp(t["win_difference"])} {interval(t["win_ci95"],True)} | {t["hp_difference"]:+.2f} {interval(t["hp_ci95"])} | {t["seconds_ratio_median"]:.4f} / {t["seconds_ratio_p95"]:.4f} | {"通过单场门槛" if mode["accepted"] else "关闭"} |')
    lines+=['','分关卡的同核等时间结果：','',
        '| 候选 | 关卡 | 配对次数 | reuse 胜率 | 候选胜率 | 胜率差及 95% CI（百分点） | HP 差及 95% CI |',
        '| --- | --- | ---: | ---: | ---: | --- | --- |']
    for mode in modes:
        for stage in ('heart','act3boss','act2boss'):
            t=mode['statistics'][stage]
            lines.append(f'| {mode["mode"]} | {stage} | {t["pairs"]} | {t["reuse_rate"]:.2%} | {t["candidate_rate"]:.2%} | {pp(t["win_difference"])} {interval(t["win_ci95"],True)} | {t["hp_difference"]:+.2f} {interval(t["hp_ci95"])} |')
    gate_names=dict(positive_win_ci='同核对照胜率差的 97.5% 区间下界 > 0',
                    minimum_gain='同核对照胜率差 ≥ 3 个百分点',
                    no_stage_regression='各关卡胜率点差非负',hp_nonnegative='总体 HP 差非负',
                    median_time='配对耗时比中位数 ≤ 1.03',p95_time='配对耗时比 P95 ≤ 1.10',
                    complete='完整配对',current_fixed_reuse_ci='原 PGO 对照胜率差的 97.5% 区间下界 > 0',
                    current_fixed_reuse_gain='原 PGO 对照胜率差 ≥ 3 个百分点')
    for mode in modes:
        failures=[gate_names[k] for k,v in mode['gates'].items() if not v]
        verdict='；'.join(failures) if failures else '无'
        t=mode['statistics']['all']
        lines+=['',f'{mode["mode"]} 未满足项：{verdict}。'+link('判定与分关卡统计',S/f'evaluation/test-{mode["mode"]}.summary.json')+' · '+link('配对原始记录',S/f'evaluation/test-{mode["mode"]}.jsonl'),
                '',f'{mode["mode"]} 的候选实际用时／分配上限的 P95 为 {t["candidate_cap_ratio_p95"]:.4f}；对照／候选总测量墙钟为 {t["reuse_seconds"]:.1f}/{t["candidate_seconds"]:.1f} 秒。总和包含跨入口并行，不是用户等待时间。']
        rows=[json.loads(line) for line in (S/f'evaluation/test-{mode["mode"]}.jsonl').read_text().splitlines()]
        sim_ratio=statistics.median(r['arms'][mode['mode']]['simulations']/max(1,r['arms']['reuse']['simulations']) for r in rows)
        calls=sum(r['arms'][mode['mode']]['value_evaluations'] for r in rows)
        lines+=['',f'搜索诊断：模型调用 {calls:,} 次，候选／同核对照模拟次数比的中位数为 {sim_ratio:.3f}。模拟计数受终局缓存、搜索路径和提前结束影响，不能将这个比值解释成独立测量的推理开销。']
    if closed:
        lines+=['','拟合误差下降没有提供通过本轮搜索采用门槛的证据。标签预算、状态信息缺失、价值引导方式与推理成本都可能影响结果；本轮没有用消融实验分离这些原因，不能将某一个原因写成失败根因。按照两轮停止条件关闭候选，不追加参数扫描。']
    lines+=['',conclusion,'',
        '## 作废版本、检查与证据账本','',
        '在候选测试前发现 prior 初版没有为从兄弟分支进入的叶子补写先验。初版计时作废；修复与原设计一致，没有增加第三种候选。反例中缺先验的分支为 4/5，修复后为 0/5，终局见证保持可执行。重建后重采全部 311 个训练／验证入口，特征、标签和分支元数据与此前一致，模型哈希一致。','',
        '| 证据类别 | 内容 | 可支持的结论 |','| --- | --- | --- |',
        '| 合成／接口检查 | 先验缺口反例；错误预算拒绝；终局回放；P300 互斥及目标外复用 | 对应契约通过 |',
        '| 历史默认回归 | 9 场对原 arena：动作、模拟次数、游戏终态／RNG 指纹一致 | 这些默认样本保持行为 |',
        '| 拟合诊断 | 25,551 个中间状态标签；79/19 家族；C++/Torch 对照 | 标签拟合和推理一致性 |',
        '| 单场开发探针 | 3 个验证入口 × 2 次，每轮候选 | 开发观察，不作采用判据 |',
        '| 单场家族隔离验收 | 88 入口、30 家族、每候选 176 配对 | 上述历史入口上的局内结果 |',
        '| 开发整局 | 0 局 | 无整局胜率结论 |',
        '| 新种子确认 | 0 局 | 无新种子整局结论 |','',
        link('默认与终局检查',S/'checks/summary.json')+' · '+link('先验反例',S/'checks/prior-regression.json')+' · '+link('P300 入口',S/'checks/p300-entry.json')+' · '+link('12 组局外价值表载入',S/'checks/p300-stage-tables.json')+' · '+link('重采一致性',S/'checks/recollection.json')+' · '+link('作废记录',S/'invalid-prior-hook-v1/reason.json'),'',
        '实验没有把未终局、异常或回放失败当成输局。本轮编译保留了来源核心既有警告；没有进行完整规则一致性审计，也没有把本轮检查称为完整引擎保证。','',
        '## 使用与复现','',
        '实验代码和模型保留供复核；候选关闭时不建议替换生产 `reuse`。',
        '',link('构建与入口说明',ROOT/'sim_patch/combat_value/README.md')+' · '+link('P300 开关',ROOT/'agent/p300_common.py')+' · '+link('模型',S/'model/value.json'),'',
        '```sh',
        'export P300_ENGINE=valuenet',
        'export P300_VALUE_MODEL=<repo-parent>/sts-rl-agent-valuenet/runs/combat-valuenet-20260927/model/value.json',
        'export P300_VALUE_MODE=prior  # 或 rollout',
        '# arm: sims32+boss12+rest+valuenet+svsel+svcard',
        '# 与 reuse/refine/fast/adaptN 互斥；工作进程请显式使用 --workers 3。','```','',
        '复核脚本使用固定来源清单和哈希绑定，配置或运行包变化会拒绝向原账本续写。`combat_value_run.py` 的单场流程最多两轮，不会启动整局。只有单场通过时才允许使用 5000000000 起、每臂至少 512 局的整局配对。']
    path=ROOT/'docs/combat-valuenet-20260927.md';path.write_text('\n'.join(lines)+'\n')
    print(path)


if __name__=='__main__': main()
