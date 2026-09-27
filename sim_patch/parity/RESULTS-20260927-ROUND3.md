# 2026-09-27 第三轮检查

本轮找到两类造成生命值差异的问题：带壳寄生怪对低血量玩家造成致命伤害后回复过量，以及旋风斩与精致折扇的结算顺序不同。工作位于 `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`。改动包含检查器、场景和检测证据；模拟器规则没有修改，没有提交或推送。验收状态为 `INCOMPLETE`。

## 带壳寄生怪的吸血超过玩家损失的生命

玩家当前生命为 5、最大生命为 80，敌人当前生命为 20。玩家使用岿然不动挡住寄生怪首回合的 21 点攻击，下一回合承受 12 点吸血攻击，并由复活道具救回。

| 场景 | 原版敌人生命 | 模拟器敌人生命 | 原版／模拟器玩家生命 |
|---|---:|---:|---:|
| 5 生命，瓶中精灵复活 | 25 | 32 | 24／24 |
| 5 生命，蜥蜴尾巴复活 | 25 | 32 | 40／40 |
| 50 生命，非致命攻击对照 | 32 | 32 | 38／38 |

原版按玩家实际损失的生命回复：玩家受到 12 点攻击，但死亡前有 5 点生命，因此敌人回复 5 点。模拟器记录了穿过格挡和减伤后的 12 点伤害，没有按玩家受击前的生命截断，导致敌人回复 12 点。两种复活方式出现相同的敌人生命差异；复活后的玩家生命吻合。非致命攻击中，被比较字段吻合。

原版依据是 [`AbstractPlayer.damage`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/characters/AbstractPlayer.java:1419>) 中的 `lastDamageTaken = Math.min(damageAmount, currentHealth)`，以及 [`VampireDamageAction`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/actions/unique/VampireDamageAction.java:34>) 用该数值构造回复动作。模拟器在 [`Player.cpp`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/audit-engine-frozen-inputs/source/src/combat/Player.cpp:300) 保存未截断的伤害，再由 [`VampireAttack`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/audit-engine-frozen-inputs/source/src/combat/Actions.cpp:99) 用于回复。

三例的起点导入、打出岿然不动和第一次结束回合没有被比较字段差异；两例反例在第二次结束回合出现首个分歧，字段为敌人生命 25 与 32。

- [原版现场捕获与比较](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-parasite-v1/report.json)
- [未加入观察导出的模拟器对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-parasite-uninstrumented-v1/report.json)
- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/parasite_round3.json)与[原版记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/parasite-overkill-original.json.gz)

## 旋风斩让精致折扇的格挡迟到

玩家以 50 生命、0 格挡开始本回合，携带精致折扇，面对四个构装体，其中钉刺机有 7 点荆棘。两张愤怒攻击无荆棘的目标，随后将旋风斩作为第三张攻击牌打出，触发遗物的 4 点格挡。

| 场景 | 原版玩家生命／格挡 | 模拟器玩家生命／格挡 |
|---|---:|---:|
| 3 能量旋风斩，精致折扇 | 33／0 | 29／4 |
| 1 能量旋风斩，精致折扇 | 47／0 | 43／4 |
| 顺劈斩替代旋风斩，精致折扇 | 43／4 | 43／4 |
| 3 能量旋风斩，无精致折扇 | 29／0 | 29／0 |

原版的旋风斩动作把每次群体伤害追加到动作队列末尾，此时精致折扇的格挡动作排在这些伤害前面。因此 4 点格挡能抵消一部分荆棘。模拟器的旋风斩动作执行伤害，将其余攻击插入队首；荆棘结算结束后才轮到遗物格挡，玩家多损失 4 点生命。

顺劈斩的原版实现把伤害动作放入队列，没有旋风斩的追加步骤，因此它的格挡在荆棘之后，两边吻合。无遗物对照用于核对旋风斩本身的伤害次数与荆棘数值。

原版调用链为 [`AbstractPlayer.useCard`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/characters/AbstractPlayer.java:1351>) → [`UseCardAction` 构造时触发遗物](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/actions/utility/UseCardAction.java:41>) → [`OrnamentalFan.onUseCard`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/relics/OrnamentalFan.java:35>)，随后 [`WhirlwindAction.update`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/actions/unique/WhirlwindAction.java:36>) 追加伤害。模拟器对应 [`WhirlwindAction` 与 `AttackAllMonsterRecursive`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/audit-engine-frozen-inputs/source/src/combat/Actions.cpp:1277)，遗物在 [`onUseCardRelics`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/audit-engine-frozen-inputs/source/src/combat/BattleContext.cpp:1848) 将格挡排到队尾。

两例反例的起点导入、第一张愤怒和第二张愤怒没有被比较字段差异；首个分歧发生在旋风斩结算后。表内生命与格挡是观察结果，动作顺序是结合两侧源码得到的根因解释；探针没有逐动作导出事件流。

- [四例原版现场捕获与比较](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-whirlwind-fan-v2/report.json)
- [未加入观察导出的模拟器对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-whirlwind-uninstrumented-v1/report.json)
- [场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/whirlwind_fan_round3.json)与[原版记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/whirlwind-fan-original.json.gz)

## 排除的夹具问题与证据边界

旋风斩的第一批实验把精致折扇留在构造后的 `counter=-1`，原版因此在第一张攻击牌就触发格挡。这个初始状态不代表正常回合开始。正式四例使用 `relic_counter:0`，对应原版 `atTurnStart` 的状态。旧输出保存在 `round3-whirlwind-fan-v1`，不纳入本轮规则缺陷或正式案例索引。这个过程暴露了起点导入检查的范围限制：尚未映射的遗物私有计数需要源码核对，起点检查通过不保证所有内部状态等价。

检查器添加 `current_hp` 场景参数，使低生命测试保留原有最大生命；既有 `hp` 参数会同时改变这两个值。参数在夹具初始化时生效，伤害与复活规则没有改动。

本轮对照端是原版 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的隔离运行时，不构成无 Mod 原版的完整验收。独立原版实例提供观察数据，模拟器初始导入后按相同命令继续，没有中途恢复原版状态。对照命中 `coverage_gap` 表示被比较字段吻合，尚未比较的字段继续列为缺口。自然对局触发率、胜率影响、其他遗物组合及完整私有状态没有验证。

运行时身份保存在各案例报告中；持久化原版记录的来源和哈希见 [provenance.json](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)，根因涉及的 13 个源文件哈希见 [源码核对记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-diagnosis/source-audit.json)。

## 验证结果

7 个正式场景各使用独立原版 JVM，其中 4 个反例、3 个对照。对同一批原版记录，带观察导出的 native 与未加入观察导出的冻结 native 得到相同的首个分歧和对照结果；因此本轮两个缺陷不依赖新增 native 观察导出。重复比较合计 14 条案例记录，不能算成 14 个独立场景或缺陷。

39 项检查器测试通过，新增测试覆盖两种复活反例、非致命对照、两种能量下的旋风斩反例、顺劈斩和无遗物对照，以及当前生命参数的范围检查。测试证明检查器能检出这些冻结版本上的差异，不表示模拟器规则修复，也不证明覆盖全部不一致。

- [本轮案例索引](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-summary/index.md)
- [测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-unit-tests-final.log)与[被测源码哈希](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-diagnosis/validation.json)
- [清理核查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-20260927/round3-cleanup-audit.json)：11 份实例清理记录的剩余进程列表为空，包含排除的 4 个夹具错误场景；进程核查没有本轮拥有的 Java 实例。
