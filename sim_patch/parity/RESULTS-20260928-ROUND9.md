# 2026-09-28 第九轮检查

本轮从[撕裂与残暴修复](REPAIR-20260928-RUPTURE-BRUTALITY.md)后的构建排查，确认一类新差异：负力量时，突破极限绕过人工制品。8 个原版场景包含 2 个反例、2 个针对性对照，以及 4 个复制暴走的排查场景；后 6 例的被比较字段吻合。新发现待修复，完整一致性状态为 `INCOMPLETE`。

工作位于隔离 worktree `sts-rl-agent-parity`，没有提交或推送。此轮增加原版样本、检测测试和报告，没有修改突破极限规则。[运行时清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/runtime.json)绑定生产及观察模块。

## 负力量的突破极限绕过人工制品

玩家带有 -3 力量，打出万能药获得 1 层人工制品，再打突破极限。原版消耗人工制品，力量保持 -3；模拟器把力量变为 -6，人工制品保持 1。普通版和升级版突破极限触发相同差异。

原版 [`LimitBreakAction`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/actions/unique/LimitBreakAction.java:23>)读取当前力量，将同等数值通过 `ApplyPowerAction` 加到玩家身上。负数的 [`StrengthPower`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/StrengthPower.java:80>)属于负面效果，[`ApplyPowerAction`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/actions/common/ApplyPowerAction.java:125>)因此检查并消耗人工制品，阻止这次额外的 -3 力量。

模拟器的 [`Actions::LimitBreakAction`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/source/src/combat/Actions.cpp:1142)调用 `player.buff<STRENGTH>(当前力量)`；[该分支](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/source/include/combat/Player.h:354)相加后限制数值范围，没有根据正负值检查人工制品。偏差同时改变攻击伤害依赖的力量和用于阻挡后续负面效果的资源。

| 场景 | 原版力量／人工制品 | 模拟器力量／人工制品 |
|---|---:|---:|
| -3 力量、1 层人工制品、普通突破极限 | -3／0 | -6／1 |
| -3 力量、1 层人工制品、升级突破极限 | -3／0 | -6／1 |
| -3 力量、没有人工制品 | -6／0 | -6／0 |
| +3 力量、1 层人工制品 | +6／1 | +6／1 |

四例最终生命为 50、能量为 2。反例起点及打出万能药后的被比较字段吻合；首个分歧在第二条命令后，为 `/legacy/player_powers`。两个对照区分力量正负和人工制品是否存在，未修改原版力量或人工制品规则。负力量为受控起点，不提供自然对局发生频率。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/limit_break_artifact_round9.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/limit-break-artifact-original.json.gz)
- [观察报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-limit-break-artifact-v1/report.json)、[生产报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-limit-break-artifact-production-v1/report.json)

## 复制暴走的怀疑未得到支持

源码中的 TODO 提示复制暴走可能漏掉首次使用后的伤害增长，因此检查双发配普通／升级暴走，并用单次暴走、双发打击作对照。四个原版场景和模拟器的状态、动作、RNG 比较吻合；额外验收直接核对暴走留在弃牌堆里的伤害增长，不把通用比较未覆盖的 `base_damage` 当成通过。

| 场景 | 两边敌人最终生命（初始 300） | 弃牌堆暴走基础伤害 |
|---|---:|---:|
| 双发 + 暴走 | 279 | 18 |
| 双发 + 升级暴走 | 276 | 24 |
| 单次暴走 | 292 | 13 |
| 双发 + 打击 | 288 | 不适用 |

这些结果排除本批场景中的复制增长错误，不能外推所有复制卡、遗物和自动出牌组合。证据作为匹配场景保留，不计入缺陷数。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/rampage_copy_round9.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/rampage-copy-original.json.gz)
- [观察报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-rampage-copy-v1/report.json)、[生产报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-rampage-copy-production-v1/report.json)

## 验证与边界

8 个场景各自使用原版 JVM 和存档副本，两个样本文件为完整捕获文件的字节复制。[来源清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)绑定逐行、场景、原版游戏、Mod 及探针身份；[源码核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-source-audit.json)绑定解释所依赖的文件。捕获记录命令边界状态，没有逐动作 Java 事件流。

| 检查 | 结果 |
|---|---|
| 当前观察与生产构建各 8 例 | 各 2 个反例、6 个被比较字段吻合的案例 |
| 本次修复前构建复核 | 相同首个分歧和对照，排除撕裂／残暴补丁引入该差异的解释 |
| 当前两种构建测试 | 各 17 项通过：2 项第九轮检测／匹配合同，15 项此前修复验收 |
| 修复前检测 | 2 项通过；负向检测通过表示识别错误，不表示完成修复 |
| 清理 | 8 个原版实例退出，剩余进程列表为空 |

- [检测代码](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/test_round9_native.py)、[修复前报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-before-repair-control-v1/report.json)
- [观察测试](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-tests-audit.log)、[生产测试](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-tests-production.log)、[修复前检测](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-tests-before-repair.log)
- [索引](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-summary/index.md)、[交付核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-validation.json)、[清理记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round9-cleanup.json)

索引的 16 条记录来自两种当前构建各 8 例，不是 16 个独立场景。范围为 Ironclad A20，排除 Prismatic Shard；原版端加载 BaseMod、CommunicationMod、SpireLabLogic 等 Mod，不构成无 Mod 原版验收。匹配案例保留 `coverage_gap`，完整动态分支、私有字段、合法动作、高阶交互和自然整局验证待完成。
