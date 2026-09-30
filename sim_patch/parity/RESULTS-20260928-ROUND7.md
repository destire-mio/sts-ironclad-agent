# 2026-09-28 第七轮检查

后续状态：本报告的两类差异由[抽牌与红头骨历史状态修复](REPAIR-20260928-DRAW-SKULL.md)处理，14 个原版场景的被比较字段吻合。下文保留发现时的证据与状态；新的待修差异见[第八轮检查](RESULTS-20260928-ROUND8.md)。

本轮从[消耗牌能力顺序与红头骨修复](REPAIR-20260928-EXHAUST-SKULL.md)后的构建继续排查，确认两类差异：抽牌回调忽略能力获得顺序，以及生命上限增加后误判红头骨先前是否生效。8 个独立原版场景包含 3 个反例、5 个对照。两类差异在修复前的构建中也能复现；完整一致性状态为 `INCOMPLETE`。

本轮增加场景、原版样本、检测测试和报告。两个新发现待修复；前一轮的修复在独立目录保留，运行时身份见[清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/runtime.json)。工作位于隔离 worktree `sts-rl-agent-parity`，没有提交或推送。

## 抽牌回调的顺序改变能量和可出牌动作

玩家携带小地精之角，按“火焰吐息 → 进化”的顺序打出能力牌，此时剩 0 能量。两个圆球行者的生命经夹具与火焰药水设置为左侧 26、右侧 6。打出 0 费的妙计，抽到灼伤；进化继续抽到虚空，火焰吐息杀死右侧敌人，小地精之角给予 1 能量并抽牌。

原版最终剩 0 能量，模拟器剩 1。两边玩家获得 2 格挡，存活敌人剩 14 生命，手牌为灼伤、虚空、打击、痛击。原版合法动作只有结束回合；模拟器多出打出打击的动作。这一差异会让搜索器选择原版当前无法执行的出牌。

原版 [`AbstractPlayer.draw`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/characters/AbstractPlayer.java:1614>) 按玩家能力列表调用 `onCardDraw`。火焰吐息与进化优先级相同，顺序来自获得顺序。本例抽到灼伤后，火焰吐息的伤害排在进化抽牌前；敌人死亡时，[小地精之角](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/relics/GremlinHorn.java:48>) 把回能动作加入队尾。进化随后抽到虚空，虚空扣能量动作进入队尾，排在回能之后：`0 → 1 → 0`。

模拟器的 [`CardManager::draw`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/source/src/combat/CardManager.cpp:423) 固定先处理进化，再处理火焰吐息。进化抽到虚空时，敌人尚未因火焰吐息死亡，虚空扣能量动作先于小地精之角回能入队：`0 → 扣除 1 后截断为 0 → 1`。上一轮通过验收的消耗牌回调与本例的抽牌回调位于不同处理路径。

| 场景 | 原版最终能量 | 模拟器最终能量 |
|---|---:|---:|
| 火焰吐息先于进化，妙计前 0 能量，有小地精之角 | 0 | 1 |
| 交换能力获得顺序 | 1 | 1 |
| 妙计前剩 1 能量 | 1 | 1 |
| 去掉小地精之角 | 0 | 0 |

前三条命令（药水与两张能力牌）后的被比较字段吻合。首个分歧出现在第四条命令后，为 `/player/energy` 和 `/legal_actions`。三个对照区分能力顺序、能量零值截断和击杀回能条件。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/draw_power_order_round7.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/draw-power-order-original.json.gz)
- [观察构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-draw-order-v1/report.json)、[生产构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-draw-order-production-v1/report.json)

## 增加生命上限错误扣除红头骨力量

玩家以 41／80 生命、0 力量开始，携带红头骨。原版捕获的 `AbstractCreature.isBloodied` 和 `RedSkull.isActive` 均为 `false`。进食杀死其中一个敌人，将最大生命从 80 增为 83，并回复 3 生命。两边生命为 44／83，原版力量保持 0，模拟器变为 -3。

原版 [`AbstractCreature.increaseMaxHp`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/core/AbstractCreature.java:188>) 修改生命上限后调用回血。回血读取先前保存的 `isBloodied`；红头骨在 [`onNotBloodied`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/relics/RedSkull.java:64>) 中检查 `isActive`，避免扣除从未给予的力量。本例开始时高于半血，没有获得红头骨的 3 力量。

模拟器的 [`increaseMaxHp`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/source/src/combat/Player.cpp:207) 先修改 `maxHp`，[`heal`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/source/src/combat/Player.cpp:221) 随后用新的上限计算 `wasBloodied`。半血线从 40 变为 41.5，当前 41 生命被当作此前已处于半血；回血至 44 后，模拟器扣除 3 力量。这里缺少的是历史生效状态，排队顺序修复无法补回该状态。

| 场景 | 原版／模拟器最终生命与上限 | 原版／模拟器最终力量 |
|---|---:|---:|
| 41／80，进食增加 3 上限 | 44／83 | 0／-3 |
| 41／80，果汁增加 5 上限 | 46／85 | 0／-3 |
| 42／80，进食，仍高于新的半血线 | 45／83 | 0／0 |
| 40／80，进食，红头骨在起点生效 | 43／83 | 0／0 |

果汁提供另一条增加生命上限的入口，说明反例不依赖进食的攻击或击杀。两个进食对照分别检查新的半血线，以及原版红头骨确实处于生效状态时的减力量。进食场景保留一个存活敌人，避免战斗终局清理掩盖状态差异。两例首个分歧均在第一条命令后，为 `/legacy/player_powers` 中的 `STRENGTH`；起点导入被比较字段吻合。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/red_skull_max_hp_round7.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/red-skull-max-hp-original.json.gz)
- [观察构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-max-hp-v1/report.json)、[生产构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-max-hp-production-v1/report.json)

## 验证与边界

8 个场景使用独立原版 JVM 与存档副本，样本是捕获文件的字节复制。[来源清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)记录场景、样本、逐行哈希、游戏和 Mod 身份；[源码核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-source-audit.json)记录解释所依赖的源码。现场观察为命令边界状态，动作先后次序来自源码核对，未逐动作导出原版事件流。

| 检查 | 结果 |
|---|---|
| 8 个场景，观察与生产构建 | 各 3 个反例、5 个被比较字段吻合的对照，首个分歧及数值吻合 |
| 修复前构建复核 | 同一批样本得到相同差异与对照，排除本次补丁引入新差异的解释 |
| 第七轮检测测试 | 两种当前构建各 2 项通过；修复前构建 2 项通过 |
| 修复验收回归 | 两种当前构建各 8 项通过，覆盖 32 个此前原版场景 |
| 实例清理 | 8 个原版实例退出，剩余进程列表为空 |

- [检测代码](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/test_round7_native.py)、[修复前构建复核报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-before-repair-control-v1/report.json)
- [当前观察构建 10 项测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-tests-audit.log)、[当前生产构建 10 项测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-tests-production.log)、[修复前构建检测日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-tests-before-repair.log)
- [本轮索引](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-summary/index.md)、[交付核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-validation.json)、[清理记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round7-cleanup.json)

索引计入当前两种构建各 8 条比较记录，共 16 条；修复前复核不增加独立场景数或缺陷数。范围为 Ironclad A20，沿用 Prismatic Shard 排除约定。对照端为原版 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的隔离逻辑运行时。结果不构成无 Mod 原版验收，不提供自然对局频率或胜率结论；私有状态对应、完整动作域、高阶交互和动态分支覆盖保留为缺口。
