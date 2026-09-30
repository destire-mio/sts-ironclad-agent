# 2026-09-27 第四轮检查

后续修复见[疼痛与虚空修复记录](REPAIR-20260927-PAIN-VOID.md)。下文保留发现时的冻结引擎结果。

本轮找到两类规则差异：疼痛漏掉撕裂的力量触发，以及虚空在特定抽牌与回能顺序下少扣 1 点能量。工作位于 `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`。改动包含检查场景、原版捕获样本和检测测试；模拟器规则没有修改，没有提交或推送。完整验收状态为 `INCOMPLETE`。

## 疼痛造成的失血漏掉撕裂力量

玩家以 50 生命开始，手里有撕裂、两张愤怒和疼痛。夹具把邪教徒生命设为 300，以免战斗结束中断观察；这个数值不是自然生成的敌人生命。打出撕裂时，疼痛的失血在撕裂能力生效前结算；两边损失 1 生命，不获得力量。撕裂生效后打出第一张愤怒，两边各损失 1 生命、造成 6 点伤害，但原版获得力量，模拟器没有获得。

| 场景 | 第一张愤怒后的原版／模拟器力量 | 整段命令后的原版／模拟器敌人生命 |
|---|---:|---:|
| 撕裂、两张愤怒、疼痛 | 1／0 | 287／288 |
| 升级撕裂、两张愤怒、疼痛 | 2／0 | 286／288 |
| 撕裂、放血、愤怒，无疼痛 | 1／1 | 293／293 |
| 两张愤怒、疼痛，无撕裂 | 0／0 | 288／288 |

两个反例中，原版在第二张愤怒结算后有 2／4 点力量，模拟器为 0；玩家生命均为 47。撕裂与放血对照的玩家生命为 47，无撕裂对照的玩家生命为 48。后续伤害差异是漏掉力量触发的后果，不计为第二个缺陷。

原版的 [`Pain.triggerOnOtherCardPlayed`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/cards/curses/Pain.java:28>) 把失血来源设为玩家，[`LoseHPAction`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/actions/common/LoseHPAction.java:36>) 将来源传给伤害对象，[`RupturePower.wasHPLost`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/RupturePower.java:32>) 检查这个来源后增加力量。

模拟器在 [`triggerOnOtherCardPlayed`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/audit-engine-frozen-inputs/source/src/combat/BattleContext.cpp:2672) 调用 `PlayerLoseHp(1)`，省略的 `selfDamage` 参数[默认为 false](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/audit-engine-frozen-inputs/source/include/combat/Actions.h:65)。[`Player::hpWasLost`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/audit-engine-frozen-inputs/source/src/combat/Player.cpp:337) 因而跳过撕裂。放血设置了 `selfDamage=true`，对应对照吻合。

首个分歧发生在第 2 条命令结束后，即第一张愤怒结算后，字段为 `/legacy/player_powers`。诊断继续执行第 3 条命令时没有重新导入原版状态，后续敌人生命差异带有前序分歧标记。两种 native 构建的力量、生命和后续伤害结果一致。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/pain_rupture_round4.json)
- [原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/pain-rupture-original.json.gz)、[观察构建回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-pain-assembled-v1/comparison/report.json)与[未加入观察导出的对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-pain-uninstrumented-v1/report.json)
- [继续执行的诊断结果](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-diagnosis/pain-continuation-audit.json)与[未加入观察导出的对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-diagnosis/pain-continuation-uninstrumented.json)

## 虚空的扣能量顺序

玩家以 0 能量开始，携带符文立方体，抽牌堆顶为虚空。打出祭品后，失血触发遗物抽牌；此时祭品给予 2 能量的动作在队列中等待。原版结算后剩 1 能量，模拟器剩 2，两边玩家生命均为 44，抽到的牌相同。

原版的 [`RunicCube.wasHPLost`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/relics/RunicCube.java:27>) 把抽牌动作插入队首。[`VoidCard.triggerWhenDrawn`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/cards/status/VoidCard.java:24>) 把扣能量动作放到队尾，因此排在祭品的回能动作后面：`0 → 获得 2 → 扣除 1 → 剩 1`。

模拟器在 [`CardManager::draw`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/audit-engine-frozen-inputs/source/src/combat/CardManager.cpp:430) 抽到虚空时执行扣能量，没有把动作排到队尾：`0 → 扣除 1，截断为 0 → 获得 2 → 剩 2`。两边对负能量的截断一致，差异来自扣能量发生的时点。原版截断规则见 [`EnergyPanel.useEnergy`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/ui/panels/EnergyPanel.java:68>)。

原版的 [`Offering.use`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/cards/red/Offering.java:36>) 和 [`Bloodletting.use`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/cards/red/Bloodletting.java:24>) 均先加入失血动作，再加入回能动作。两者可用于区分祭品自身的后续抽牌是否为必要条件。初始 1 能量的对照用于检查零值截断这个触发条件；无符文立方体的对照让虚空在祭品回能后抽出。

| 场景 | 原版最终能量 | 模拟器最终能量 | 原版／模拟器玩家生命 |
|---|---:|---:|---:|
| 0 能量、符文立方体、祭品 | 1 | 2 | 44／44 |
| 0 能量、符文立方体、放血 | 1 | 2 | 47／47 |
| 0 能量、无符文立方体、祭品 | 1 | 1 | 44／44 |
| 1 能量、符文立方体、祭品 | 2 | 2 | 44／44 |

放血得到相同的原版 1／模拟器 2 能量差异，说明祭品自身的抽牌不是必要条件。两个对照的被比较字段吻合：没有遗物时，祭品回能后抽到虚空；起始能量为 1 时，模拟器提前扣除的 1 点没有被零值截断。

两个反例起点导入后的被比较字段吻合，首个分歧出现在第 1 条命令结束后，字段为 `/player/energy`。能量值和抽牌结果是观察事实，上述队列顺序依据两侧源码解释；没有逐动作导出原版事件流。这个缺陷与回合末虚无牌洗牌的 BaseMod 差异分开记录，本轮场景没有结束回合。

- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/void_energy_round4.json)
- [原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/void-energy-original.json.gz)、[观察构建回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-void-assembled-v1/comparison/report.json)与[未加入观察导出的对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-void-uninstrumented-v1/report.json)

## 执行故障与证据边界

疼痛批次的两个对照在原版启动握手时超过 90 秒，没有得到案例起点或执行战斗命令。这两条 `original_error` 保存在 `round4-pain-rupture-v1`，不计为规则差异或通过。日志显示超时发生在 Mod 和游戏资源初始化期间。原版启动等待上限改为 180 秒，并写入案例身份记录；后续战斗命令超时与 native 案例超时不变。两个对照在新实例中补跑后，被比较字段吻合。

疼痛的持久样本从首批两个成功案例和补跑的两个对照组成；虚空的持久样本来自补跑批次后四例。装配过程复制捕获行，不修改状态、命令或响应。[provenance.json](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json) 保存原始批次路径、文件哈希、行号、行内容哈希、运行时身份及排除的启动失败。源码解释涉及的 15 个文件哈希见 [源码核对记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-diagnosis/source-audit.json)。

本轮对照端为原版 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的隔离运行时，不构成无 Mod 原版的完整验收。模拟器从原版案例起点导入一次，随后执行相同命令。`coverage_gap` 表示被比较字段吻合，但私有状态、输入域和动态分支覆盖存在缺口。受控案例没有给出自然对局触发率或胜率影响。

## 验证结果

8 个正式场景使用独立原版 JVM，其中 4 个反例、4 个对照，对应 2 类新增规则缺陷。相同原版记录在观察构建与未加入观察导出的冻结 native 中，得到相同的首个分歧、字段值和对照结果。本轮索引纳入两种构建各 8 条回放记录，共 16 条；现场捕获时的重复比较作为来源证据，不增加独立场景数或缺陷数。

41 项检查器测试通过，无跳过。新增测试覆盖普通／升级撕裂、放血与无撕裂对照、继续执行后的伤害后果、祭品／放血两种虚空反例，以及无遗物／初始 1 能量对照。这些测试验证检查器能检出冻结模拟器中的差异，不表示模拟器规则修复，也不证明找完所有不一致。

- [本轮案例索引](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-summary/index.md)
- [测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-unit-tests.log)与[样本、源码及两种构建核查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-diagnosis/validation.json)
- [清理核查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round4-cleanup-audit.json)：10 个原版实例包含 8 个正式场景与 2 个启动失败实例，剩余进程列表为空；进程核查没有本轮拥有的 Java 实例。
