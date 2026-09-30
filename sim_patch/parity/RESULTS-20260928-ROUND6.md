# 2026-09-28 第六轮检查

后续修复见[消耗牌能力顺序与红头骨修复](REPAIR-20260928-EXHAUST-SKULL.md)。下文保留发现时的冻结引擎结果。

本轮在群攻／鸟面瓮修复版本中确认两类新差异：消耗牌触发能力时忽略获得顺序，以及红头骨在致命伤与复活之间的力量结算顺序错误。8 个独立原版场景包含 3 个反例、5 个对照；完整一致性验收为 `INCOMPLETE`。

工作位于 `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`。本轮增加场景、原版样本、检测测试和报告，没有修改模拟器规则，没有提交或推送。[运行时核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-runtime.json)确认 84 个源码文件及 3 个二进制文件与上一轮修复清单吻合。

## 消耗牌触发能力的顺序改变伤害目标

玩家按“无惧疼痛 → 黑暗之拥 → 势不可挡 → 火焰吐息”的顺序打出能力牌，然后打出万能药。万能药消耗时，无惧疼痛给予 3 格挡，黑暗之拥抽到灼伤；格挡触发势不可挡的随机伤害，灼伤触发火焰吐息的全体伤害。

受控场景使用两个圆球行者，将当前生命设为 26。火焰药水对右侧敌人造成 20 伤害，构成左侧 26、右侧 6 的起点。六条命令中，药水与四张能力牌结束后的被比较字段吻合；首个分歧出现在打出万能药后，即命令索引 5。

原版的 [`CardGroup.moveToExhaustPile`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/cards/CardGroup.java:833>) 按玩家能力列表调用 `onExhaust`。无惧疼痛与黑暗之拥使用相同默认优先级，原版排序保留获得顺序。因此，这个场景先排入加格挡，再排入抽牌；[`JuggernautPower`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/JuggernautPower.java:31>) 与 [`FireBreathingPower`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/FireBreathingPower.java:36>) 按此顺序把伤害动作加入队尾。

在本次随机数状态下，势不可挡选中右侧敌人，造成 5 伤害，将其生命从 6 降到 1；火焰吐息随后造成全体 6 伤害。右侧敌人死亡，左侧剩 20 生命。

模拟器的 [`triggerAndMoveToExhaustPile`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/source/src/combat/BattleContext.cpp:2853) 固定先处理黑暗之拥，再处理无惧疼痛。火焰吐息伤害因此排在势不可挡前面，先杀死右侧敌人；势不可挡从存活敌人中选目标，此时目标池剩左侧敌人，造成 5 伤害，左侧生命变为 15。首个分歧字段为 `/monsters/0/hp`，被比较的 RNG 状态没有分歧。

| 场景 | 原版最终敌人生命：左／右 | 模拟器最终敌人生命：左／右 |
|---|---:|---:|
| 无惧疼痛先于黑暗之拥，抽灼伤 | 20／0 | 15／0 |
| 同上，势不可挡升级为 7 伤害 | 20／0 | 13／0 |
| 黑暗之拥先于无惧疼痛，顺序对照 | 15／0 | 15／0 |
| 无惧疼痛先于黑暗之拥，改抽打击 | 26／1 | 26／1 |

四个场景结束后，双方玩家格挡为 3，抽到的牌吻合。升级版的 7 点差距来自相同的目标变化，不计作第三类缺陷。交换能力获得顺序的对照用于区分固定顺序与伤害数值错误；改抽打击的对照移除了抽牌触发伤害的条件。场景使用设置的敌人生命与 6 点初始能量，不是自然整局样本。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/exhaust_power_order_round6.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/exhaust-power-order-original.json.gz)
- [现场捕获与观察构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-exhaust-order-v1/report.json)、[生产构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-exhaust-order-production-v1/report.json)

## 红头骨与复活在力量上限处结算不同

玩家以 50／80 生命、999 力量开始，携带红头骨、神圣树皮和瓶中精灵。场景给邪教徒设置 100 力量以造成致命伤；两次结束回合后，瓶中精灵回复 48 生命，跨过红头骨的半血阈值。原版最终力量为 999，模拟器为 996；生命、药水消耗及其余被比较字段吻合。

原版 [`AbstractPlayer.damage`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/characters/AbstractPlayer.java:1458>) 在玩家生命降到半血以下时触发红头骨，随后处理瓶中精灵复活。[`RedSkull.onBloodied`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/relics/RedSkull.java:51>) 将加 3 力量动作插入队首，尚未执行；复活调用 [`AbstractCreature.heal`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/core/AbstractCreature.java:375>)，生命超过半血后，`onNotBloodied` 把减 3 力量动作插到它前面。因此原版力量按 `999 → 996 → 999` 结算。

模拟器的 [`Player::hpWasLost`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/source/src/combat/Player.cpp:372) 在失血时执行加 3，受上限限制保持 999；复活调用 [`Player::heal`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/source/src/combat/Player.cpp:212)，再执行减 3，结果为 996。双方存在力量上限，差别是加减力量的时点。

| 场景 | 原版／模拟器复活生命 | 原版／模拟器最终力量 |
|---|---:|---:|
| 999 力量，红头骨＋树皮＋精灵 | 48／48 | 999／996 |
| 改为 10 力量 | 48／48 | 10／10 |
| 999 力量，去掉神圣树皮 | 24／24 | 999／999 |
| 999 力量，去掉红头骨 | 48／48 | 999／999 |

三个对照分别检查力量上限、复活后跨过半血、红头骨三个条件。反例起点与第一次结束回合后的被比较字段吻合，首个分歧出现在第二次结束回合后，字段为 `/legacy/player_powers` 中的 `STRENGTH`。本轮没有测量这种边界组合在自然对局中的出现频率。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/red_skull_revive_round6.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/red-skull-revive-original.json.gz)
- [现场捕获与观察构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-red-skull-v1/report.json)、[生产构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-red-skull-production-v1/report.json)

## 证据与验证

8 个场景使用独立原版 JVM 和存档副本。持久样本是捕获文件的字节复制，没有改写状态、命令或响应。[来源清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)保存场景、原版样本、逐行内容、游戏与 Mod 身份、清理记录及捕获构建哈希。[源码核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-source-audit.json)保存上述解释涉及的 23 个 Java／C++ 文件哈希。队列解释来自源码；现场观察的是命令结束后的状态，没有逐动作导出原版事件流。

| 检查 | 结果 | 含义 |
|---|---|---|
| 8 个原版场景 | 3 个 `mismatch`，5 个 `coverage_gap` 对照 | 对照的被比较字段吻合，缺口保留 |
| 观察构建与生产构建 | 首个分歧、数值及对照分类吻合 | 差异不依赖新增观察导出 |
| 第六轮检测测试 | 两种构建各 2 项通过，包含 8 个场景 | 检查器检出本轮差异，不表示规则修复 |
| 疼痛／虚空、群攻／鸟面瓮修复验收 | 两种构建各 5 项通过，包含此前 20 个原版场景 | 先前修复的被测行为吻合 |
| 冻结旧版检查器回归 | 41 项通过，无跳过 | 检测与回归入口通过 |
| 原版实例清理 | 8 个实例的剩余进程列表为空 | 本轮拥有的实例退出 |

- [第六轮检测代码](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/test_round6_native.py)
- [观察构建 7 项测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-tests-audit.log)、[生产构建 7 项测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-tests-production.log)、[冻结检查器日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-tests-frozen-checker.log)
- [本轮索引](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-summary/index.md)、[交付核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-validation.json)、[清理记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round6-cleanup-audit.json)

索引包含两种构建各 8 条比较记录，共 16 条；独立原版场景数为 8，新增缺陷类别数为 2。本轮对照端为原版 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的隔离逻辑运行时，范围为 Ironclad A20，沿用 Prismatic Shard 排除约定。结果不构成无 Mod 原版验收，不证明所有可达状态一致；私有状态、完整动作域、高阶交互、自然整局和动态分支覆盖保留为缺口。两个发现待修复。
