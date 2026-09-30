# 2026-09-28 第八轮检查

后续状态：两类差异由[撕裂与残暴修复](REPAIR-20260928-RUPTURE-BRUTALITY.md)处理，8 个原版场景的被比较字段吻合。下文保留发现时的证据与状态；新的待修差异见[第九轮检查](RESULTS-20260928-ROUND9.md)。

本轮从[抽牌与红头骨历史状态修复](REPAIR-20260928-DRAW-SKULL.md)后的构建继续排查，确认两类差异：撕裂加力量未进入动作队列，残暴的抽牌与失血顺序颠倒。8 个独立原版场景包含 4 个反例、4 个对照。观察、生产与修复前构建复现相同差异，两个发现待修复，完整一致性状态为 `INCOMPLETE`。

工作位于隔离 worktree `sts-rl-agent-parity`，没有提交或推送。本轮新增场景、捕获样本、检测测试和报告，没有修改这两处模拟器规则；运行时身份见[清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/runtime.json)。

## 撕裂与复活在力量上限附近少算力量

玩家生命为 5／80，携带红头骨、神圣树皮和瓶中精灵。夹具力量设置为 999，红头骨启动后的力量受上限约束保持 999。打出撕裂，再打祭品，失去 6 生命触发复活，回复到 48／80，并失去红头骨的 3 力量。

原版 [`RupturePower.wasHPLost`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/RupturePower.java:32>)把加力量动作加入队首；复活回血时，[红头骨](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/relics/RedSkull.java:64>)随后把减 3 力量动作加入队首，所以先减后加。普通撕裂结果为 `999 → 996 → 997`，升级撕裂结果为 998。

模拟器在 [`Player::hpWasLost`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/source/src/combat/Player.cpp:345)中直接增加力量，增加量被 999 上限截掉，红头骨的减力量动作随后执行，结果为 996。前轮红头骨排队修复没有覆盖撕裂的这条路径。

| 场景 | 原版最终力量 | 模拟器最终力量 |
|---|---:|---:|
| 999 力量，撕裂 +1，红头骨与复活 | 997 | 996 |
| 999 力量，升级撕裂 +2，红头骨与复活 | 998 | 996 |
| 低力量对照，夹具设 10、启动后 13 | 11 | 11 |
| 去掉红头骨的上限对照 | 999 | 999 |

四例最终生命为 48，能量为 4。起点与第一条命令的被比较字段吻合；反例首个分歧在第二条命令后，为 `/legacy/player_powers` 中的力量。低力量对照与移除红头骨对照区分上限截断和复活减力量的共同影响。这是受控边界场景，不说明自然对局出现频率。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/rupture_revive_round8.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/rupture-revive-original.json.gz)
- [观察报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-rupture-revive-v1/report.json)、[生产报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-rupture-revive-production-v1/report.json)

## 残暴、混乱与以血还血多花 1 能量

玩家打出残暴后结束回合，异蛇通过凝视施加混乱。下回合先抽五张伤口，残暴额外抽到以血还血。原版 [`BrutalityPower`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/BrutalityPower.java:35>)先排抽牌，再排失血；[混乱](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/ConfusionPower.java:36>)将这张牌随机定为 1 费，随后失去 1 生命，[以血还血](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/cards/red/BloodForBlood.java:28>)降为 0 费。

模拟器的[残暴处理](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/source/src/combat/Player.cpp:776)先排失血，再排抽牌。牌在抽牌堆里先降费，随后混乱重新随机定为 1 费，结果比原版高 1。两边消耗相同 RNG；差异来自操作顺序，未用相同种子替代状态检查。

| 场景 | 原版／模拟器抽到牌的费用 | 打出后原版／模拟器剩余能量 | 最终生命 |
|---|---:|---:|---:|
| 残暴 + 混乱 + 以血还血 | 0／1 | 3／2 | 49 |
| 以血还血升级 | 0／1 | 3／2 | 49 |
| 去掉混乱，以邪教徒为敌人 | 3／3 | 0／0 | 49 |
| 钨合金棍阻止残暴失血 | 1／1 | 2／2 | 50 |

反例首个分歧位于结束回合后的手牌 `cost` 与 `base_cost`；起点与打出残暴后的被比较字段吻合。通用重放在首个分歧处停止，检测测试另从起点执行完整三条命令，在不回填原版状态的情况下核对出牌后能量差。去掉混乱和阻止失血的对照均吻合。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/brutality_confusion_round8.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/brutality-confusion-original.json.gz)
- [观察报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-brutality-confusion-v1/report.json)、[生产报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-brutality-confusion-production-v1/report.json)

## 验证与边界

8 个场景使用独立原版 JVM 和存档副本，样本为捕获文件的字节复制。[来源清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)记录逐行哈希、游戏及 Mod 身份；[源码核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-source-audit.json)绑定本报告的解释。捕获观察点为命令边界，动作内部顺序依据源码，没有逐动作 Java 事件流。

| 检查 | 结果 |
|---|---|
| 当前观察与生产构建各 8 例 | 各 4 个反例、4 个被比较字段吻合的对照；首个分歧和数值一致 |
| 本次修复前构建 | 同一批样本得到相同反例和对照，排除本次补丁引入这两类差异的解释 |
| 当前两种构建的测试 | 各 15 项通过：2 项新差异检测、13 项修复验收；后者覆盖 46 个原版场景和历史状态导入 |
| 修复前差异检测 | 2 项通过；通过表示发现错误，不表示错误完成修复 |
| 清理 | 8 个原版实例退出，剩余进程列表为空 |

- [检测代码](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/test_round8_native.py)、[修复前报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-before-repair-control-v1/report.json)
- [观察测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-tests-audit.log)、[生产测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-tests-production.log)、[修复前检测日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-tests-before-repair.log)
- [本轮索引](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-summary/index.md)、[交付核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-validation.json)、[清理记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round8-cleanup.json)

索引包含当前两种构建的 16 条比较记录，不是 16 个独立场景。范围为 Ironclad A20，排除 Prismatic Shard；原版端加载 BaseMod、CommunicationMod、SpireLabLogic 等 Mod，不构成无 Mod 原版验收。对照结果保留 `coverage_gap`，不提供自然整局频率或胜率结论，完整动态分支、私有状态、动作域与高阶交互覆盖待完成。
