# 2026-09-28 第五轮检查

本轮在疼痛／虚空修复版本中确认两类差异：部分群攻计算伤害的时点错误，以及鸟面瓮回血早于疼痛失血。8 个独立原版场景包含 4 个反例、4 个对照。检查范围为 Ironclad A20，沿用 Prismatic Shard 排除约定；完整一致性验收为 `INCOMPLETE`。

工作位于 `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`。本轮增加场景、原版样本、检测测试和报告，没有修改模拟器规则，没有提交或推送。[运行时核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/runtime.json)确认使用上一轮修复后的构建，84 个规则、头文件和绑定源码的哈希与修复清单吻合。

## 群攻把疼痛触发后的力量算进当前牌

玩家以 50 生命开始，手里有撕裂、顺劈斩、疼痛。打出撕裂后，双方生命为 49、力量为 0。打出顺劈斩时，疼痛使生命变为 48，撕裂使力量变为 1；原版顺劈斩造成 8 点伤害，模拟器造成 9 点。力量和失血吻合，伤害分歧出现在第二条命令结束后。

原版在 [`AbstractPlayer.useCard`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/characters/AbstractPlayer.java:1339>) 中调用 `calculateCardDamage`，然后调用卡牌 `use`，最后触发手牌中疼痛的失血。顺劈斩和死亡收割把当时的 `multiDamage` 交给伤害动作。因此，疼痛触发的力量能影响后续牌，但不改变当前牌的这份伤害。

模拟器的 [`useCard`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/source/src/combat/BattleContext.cpp:890) 创建攻击动作后，将疼痛失血[加入队首](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/source/src/combat/BattleContext.cpp:2672)。[`AttackAllEnemy(int)`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/source/src/combat/Actions.cpp:28) 和 [`ReaperAction`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/source/src/combat/Actions.cpp:1171) 在动作执行时读取力量计算伤害，此时疼痛和撕裂完成结算，导致当前牌多算 1 点力量。愤怒在创建动作时保存计算后的伤害，对照吻合。

| 场景 | 原版／模拟器敌人生命 | 原版／模拟器玩家生命 | 原版／模拟器力量 |
|---|---:|---:|---:|
| 撕裂、顺劈斩、疼痛 | 292／291 | 48／48 | 1／1 |
| 撕裂、死亡收割、疼痛 | 296／295 | 52／53 | 1／1 |
| 撕裂、顺劈斩，无疼痛 | 292／292 | 50／50 | 0／0 |
| 撕裂、愤怒、疼痛 | 294／294 | 48／48 | 1／1 |

夹具使用 300 生命的邪教徒，目的是避免战斗结束中断观察，这不是自然生成的敌人生命。死亡收割多回的 1 点生命来自同一处伤害差异，不计作另一类缺陷。疼痛失血来源的修复继续成立；本轮是在力量触发正确的版本上发现后续伤害计算问题。

确认范围为表中卡牌与操作序列。其他调用这些动作的牌属于待测范围，没有用源码相似性代替原版复现。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/pain_aoe_round5.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/pain-aoe-original.json.gz)
- [现场捕获与观察构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round5-pain-aoe-v1/report.json)、[未加入观察导出的构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round5-pain-aoe-production-v1/report.json)

## 鸟面瓮在疼痛失血前回血

玩家最大生命为 80，携带鸟面瓮，手里有燃烧和疼痛。以 80 生命打出燃烧，原版按 `80 → 疼痛扣至 79 → 鸟面瓮回复至 80` 结算；模拟器按 `80 → 回复受上限限制，保持 80 → 疼痛扣至 79` 结算。最终生命差 1。

原版 [`BirdFacedUrn.onUseCard`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/relics/BirdFacedUrn.java:27>) 将回血动作放到队首。该回调来自 [`UseCardAction` 构造函数](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/actions/utility/UseCardAction.java:31>)，随后 [`Pain.triggerOnOtherCardPlayed`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/cards/curses/Pain.java:28>) 将失血动作插到它前面。

模拟器在 [`onUseCardRelics`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/source/src/combat/BattleContext.cpp:1885) 中调用 `p.heal(2)`，随后创建疼痛失血动作。双方的生命上限规则吻合，差别在于回血和失血的次序。

| 场景 | 起始生命／上限 | 原版最终生命 | 模拟器最终生命 |
|---|---:|---:|---:|
| 鸟面瓮、燃烧、疼痛 | 80／80 | 80 | 79 |
| 鸟面瓮、金属化、疼痛 | 79／80 | 80 | 79 |
| 鸟面瓮、燃烧、疼痛，受伤对照 | 50／80 | 51 | 51 |
| 鸟面瓮、燃烧，无疼痛 | 80／80 | 80 | 80 |

两个反例的起点导入字段吻合，第一条命令后的首个分歧为 `/player/hp`。从 50 生命开始时，两种顺序没有触及生命上限，结果吻合；去掉疼痛时，两边在满血状态下回血，结果吻合。没有据此推算自然对局中的触发频率或胜率影响。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/urn_pain_round5.json)、[原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/urn-pain-original.json.gz)
- [现场捕获与观察构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round5-urn-pain-v1/report.json)、[未加入观察导出的构建报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round5-urn-pain-production-v1/report.json)

## 证据与验证

两批场景使用 8 个独立原版 JVM 和存档副本。样本文件是完整捕获文件的字节复制，没有改写状态、命令或响应。[来源清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)记录每行哈希、每个原版实例的游戏及 Mod 身份、场景文件哈希和清理结果。[源码核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/source-audit.json)保存结算顺序解释所用的 15 个源码文件哈希。队列次序来自源码核对，现场观察的是操作结束后的状态，没有逐动作导出原版事件流。

原版记录在修复后的两种 native 构建中得到相同的反例与对照结果。本轮索引收录两种构建各 8 条比较记录，共 16 条；独立原版场景数为 8，缺陷类别数为 2。

| 检查 | 结果 | 含义 |
|---|---|---|
| 第五轮 8 个原版场景 | 4 个 `mismatch`，4 个 `coverage_gap` 对照 | 对照的被比较字段吻合；覆盖缺口保留 |
| 观察构建与生产构建 | 首个分歧、数值和对照分类吻合 | 差异不依赖新增观察导出 |
| 第五轮检测测试 | 两种构建各 2 项通过 | 检查器检出新差异；不表示规则修复 |
| 上轮疼痛／虚空验收 | 两种构建各 2 项通过，覆盖此前 8 个原版场景 | 先前修复的被测行为吻合 |
| 冻结旧版检查器测试 | 41 项通过，无跳过 | 旧版差异检测与检查器回归保持通过 |
| 原版实例清理 | 8 个实例的剩余进程列表为空 | 本轮拥有的原版实例退出 |

- [第五轮检测代码](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/test_repaired_native.py)
- [观察构建测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/tests-repaired-audit.log)、[生产构建测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/tests-repaired-production.log)、[冻结检查器日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/tests-frozen-checker.log)
- [本轮索引](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/round5-summary/index.md)、[交付核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/validation.json)、[清理记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260928/cleanup-audit.json)

对照端为原版 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的隔离逻辑运行时。结果不构成无 Mod 原版验收，也不证明所有可达状态一致。私有状态、完整动作域、高阶交互、自然整局和动态分支覆盖保留为缺口。本轮两个发现待修复。
