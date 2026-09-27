# 2026-09-27 第二轮检查

本轮新增一个有伤害结果的模拟器差异：**暴走同时受到双发、复制药水影响时，第二张待执行副本缺少伤害增长。** 检查器及证据留在 `sts-rl-agent-parity` worktree，分支 `codex/original-simulator-parity-20260927`。模拟器规则没有修改，没有提交或推送。验收保持 `INCOMPLETE`。

## 暴走与两种复制效果

场景使用 300 生命的敌人、3 点能量、手牌双发和暴走，以及一瓶复制药水。操作为：打出双发 → 使用复制药水 → 对敌人打出暴走。

| 场景 | 原版伤害 | 模拟器伤害 | 原版剩余生命 | 模拟器剩余生命 |
|---|---:|---:|---:|---:|
| 普通暴走，两种复制效果 | 39 | 34 | 261 | 266 |
| 升级暴走，两种复制效果 | 48 | 40 | 252 | 260 |
| 普通暴走，双发对照 | 21 | 21 | 279 | 279 |
| 普通暴走，复制药水对照 | 21 | 21 | 279 | 279 |

普通暴走的原版伤害链为 8、13、18；模拟器为 8、13、13。升级牌对应 8、16、24 与 8、16、16。表内伤害由敌人生命差计算；分次伤害链由原版和模拟器的处理代码解释，探针没有逐次导出伤害事件。

原版 `ModifyDamageAction` 根据同一个卡牌 UUID 更新战斗中的实例，其中包含等待出牌的副本。模拟器把复制牌按当时的数值放入出牌队列；第一张副本增长伤害后，`findAndUpgradeSpecialData` 更新牌堆中的实体，没有更新另一张等待执行的副本。该副本使用旧数值，因此普通牌少 5 点、升级牌少 8 点。牌堆中最后保留的暴走伤害数值吻合，单看最终卡牌数据会漏掉敌人受到的伤害差异。

四个场景使用四个独立原版 JVM。普通叠加场景有另一份独立捕获作为复现；正式四例以 `round2-rampage-copies-v2` 为准。未加入 `parity_state` 观察代码的冻结性能版产生相同的两个伤害差异，排除了新增 native 观察导出造成差异的解释。受控起点通过当前比较字段的导入检查；自然对局触发率及胜率影响没有测量。

- [四例现场报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-rampage-copies-v2/report.json)
- [未加入观察代码的模拟器对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-rampage-uninstrumented-v1/report.json)
- [场景文件](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/rampage_copies_round2.json)
- [保留在代码目录的原版记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/rampage-copies-original.json.gz)和[来源哈希](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)

## 虚无牌顺序：对照端的 Mod 改变了规则

本机原版 JAR 运行在 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 组成的测试环境中。BaseMod 的 `ConsistentEtherealPatch` 修改了 `DiscardAtEndOfTurnAction`：原版源码调用共享随机源洗牌，补丁改用 `游戏种子 + 楼层 × 55 + 回合数` 初始化局部 Java 随机源，再进行洗牌。模拟器按手牌倒序执行虚无牌消耗。

在三个独立 JVM 中，将手牌设为眩晕、进阶之灾、灵体，结束回合后，带补丁的原版消耗顺序为进阶之灾、眩晕、灵体；模拟器为灵体、进阶之灾、眩晕。增加枯木树枝、黑暗之拥、无惧疼痛的场景出现相同顺序差异。单张虚无牌的对照中，被比较字段吻合。

从测试实例的 BaseMod 副本中移除这一补丁的两个类后，两次三张牌场景及单张牌场景的牌序与模拟器吻合。三张牌场景中，Java 共享随机源的状态发生变化，说明无补丁路径使用了该随机源；这两次相同的顺序不证明随机规则与固定倒序等价。移除补丁的实例保留其余 Mod，不能称为无 Mod 原版。

第一轮 8 个眩晕实例顺序异常，在各自首个分歧前的手牌、种子、楼层、回合数上，按 BaseMod 的洗牌规则计算出的 UUID 顺序与原版记录逐例吻合。该证据支持共同的补丁规则解释；8 个案例不计为 8 个独立缺陷，也不计为 8 个无 Mod 原版规则错误。

- [带补丁重复实验](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-ethereal-v1/report.json)
- [移除单个补丁的对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-reference-profile-v1/report.json)
- [8 个历史案例的规则预测](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-diagnosis/ethereal-attribution.json)
- [运行时、随机源及源文件哈希](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-diagnosis/reference-audit.json)

## 两例随机数误报与观察点修正

巫毒娃娃、远古茶具的两例 `cardRandomRng` 差异来自旧的 native 探针：构造战斗对象后，探针读取了战斗外 `GameContext` 的随机数；原版返回战斗中的随机数。开启战斗明细读取 `BattleContext` 后，两例卡牌随机数吻合。远古茶具的计数显示差异 `-1` 与 `-2` 保留为原始表示差异。

检查器对显式 `ops` 进入战斗且观察点仍在战斗的案例读取战斗状态；胜利退出战斗后读取整局状态。测试包含战后回血对照，避免读取旧战斗生命而漏掉燃烧之血等遗物的回复。914 个历史战斗外案例重跑后得到 597 个覆盖缺口记录、317 个原始观察差异；两例随机数差异消失，其中茶具案例因计数差异保留在差异组。事件和存档路径上的 47 例洗牌随机数差异尚需观察时点核对。

- [两例独立原版捕获](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-outside-rng-v1/comparison/report.json)
- [修正后的 914 例报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-outside-v3/report.json)

## 整局与数值边界

检查器增加 `natural --continue-after-mismatch`。该模式保留首个分歧，记录后续每个分歧，并标明是否受到前序分歧影响；中途没有恢复或导入原版状态。

种子 129 的历史原版记录包含 1003 次请求与响应。本次执行 1002 条游戏命令、检查 909 个观察点，走到第 51 层失败结局，得分 1786。83 个观察点的差异均为赌徒药水的回合弃牌计数，没有新字段差异；这不等于 83 个缺陷。回放采用历史原版响应，不能当作本轮新生成的整局原版证据，也不能证明其他种子一致。

力量 999 使用突破、敌方力量 -998 使用缴械两个边界中，被比较字段吻合。早期正力量案例设置了超过敌人最大生命的当前生命，该人工条件不作为自然可达状态依据；后续用正常生命的敌人重跑突破上限场景，结果吻合。

- [整局继续回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-natural-continue-v1/report.json)
- [正常生命状态下的力量上限对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-strength-valid-v1/report.json)
- [交互与负力量边界](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-interactions-v1/report.json)

## 验证和保留的边界

36 项检查器测试通过，覆盖新伤害反例及单复制对照、首个分歧后检出新的生命差异、报告索引保留后续字段、战斗与战后状态归属、补丁副本隔离、未知场景参数拒绝等。检查器未知参数拒绝用于防止 `upgraded` 一类被原版夹具忽略的拼写让场景名称与实际测试对象不符。

[本轮索引](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-summary/index.md)包含 936 条案例记录，含历史重跑和重复对照，不能换算为独立规则覆盖。[测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-unit-tests-final.log)保留验证结果。

19 份实例清理记录的剩余进程列表为空，进程核查没有本轮拥有的 Java 实例，见[清理记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round2-cleanup-audit.json)。

一次捕获因升级参数拼写错误被中断，未执行的升级场景不计为验证；正式场景改为 `upgrades:1` 并从新 JVM 捕获。战斗外观察调整的中间版本误读了战后生命，由战后回血对照发现，正式历史重跑使用 `round2-outside-v3`。中间输出保留原名，没有覆盖成正式证据。

完整动态分支覆盖、私有状态映射、选牌合法域、所有 Mod 对规则的修改、其他种子与高阶组合、无界操作序列仍属于缺口。工具没有证明找到所有不一致。
