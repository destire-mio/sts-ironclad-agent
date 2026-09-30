# 原版接入：RNG 导出可行性检查

日期：2026-09-27。状态：**触发用户指定的 RNG 停止条件，等待后续决定**。

后续状态：用户授权“修复、在此工作树提交推送、完成后继续找”。已知持久 RNG 导出缺口的修复和原版验证见 [修复报告](live-original-rng-fix-20260927.md)。下文保留首次检查时的事实，不代表修复后的状态。

## 结论

现有导出没有满足“全部 RNG 状态”的要求。Steam 补丁导出 6 条战斗 RNG；复用对齐 oracle 后，在本机原版 JAR 中读到了 13 条地牢 RNG 以及两个共享随机源，但发现 oracle 遗漏 `NeowEvent.rng`。模拟器的现有战斗入口接收上述 6 条战斗 RNG，没有为其余随机源建立完整的导入、预测、执行后比较和 SL 恢复契约。

**这是现有导出契约的缺口，不是发现了 JAR 禁止读取这些字段。** `NeowEvent.rng` 是公开静态字段，地牢 RNG 的内部两字状态具有读取接口；补充已知导出的路线具备源码依据。共享随机源的消费过程、读档恢复与真实画面运行下的时序尚无完整验收，不能用“种子相同”替代验证。

因此，本次工作停在小规模可行性探针，没有开展 20 局工程与评测。完成整局数为 **0**，胜局数和胜率为 **未测量**，不是 0% 胜率。

## 实测与范围

| 项目 | 结果 |
|---|---|
| 独立工作树 | `/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-live-original` |
| 分支与基线 | `codex/live-original-evaluation-20260927`；`8f9d33ee83c23fb2c9989d0e2a090fd1e55eafe1` |
| 运行种子 | 整数 `5100000000`，原版种子串 `2S3KFAQ`；响应中的整数种子经核对 |
| 原版 | 本机安装的 12-18-2022 JAR，与隔离实例 JAR 的 SHA-256 相同 |
| JAR SHA-256 | `dd60a613a6178e08f1a57bcb8d5747e33c21fd49e743b88d76e9d74042803b2a` |
| 执行路径 | A20 Ironclad 自然开局 → 涅奥 → 地图 → 第 1 层战斗 → 结束第 1 回合 |
| 首战怪物 | `SpikeSlime_S`、`AcidSlime_M` |
| 输入 | `start ironclad 20 2S3KFAQ`、4 次 `choose 0`、`end`，另有观察请求 |
| RNG 观察 | 战斗前与结束回合后均导出 13 条地牢 RNG；首战重复观察的 RNG 相同 |
| SL | 0 次；本次没有进行读档对照实验 |
| 资源 | 1 个自有原版 JVM；模拟器决策进程为 0，低于 3 个上限 |
| 清理 | 自有 JVM 退出，`cleanup.json` 中 `remaining=[]`；用户原有 9 个实验 worker 在结束核对时存活 |

运行使用本机原版 JAR，加上 BaseMod、CommunicationMod、SpireLabObserver、SpireLabLogic 与采集探针。SpireLabLogic 使用固定逻辑帧、无画面渲染。**这证明原版 Java 逻辑及命令通路能够运行，不构成 Steam 图形界面整局运行验收，也不构成无 Mod 原版等价性证明。**

本次 `choose 0` 是可行性检查输入，没有调用 `sims32+boss12+rest+reuse+svsel+svcard`。用户提供的约 24.3% 模拟器成绩没有在本次复测。P300 文件、父网络、价值表及性能运行时尚未作为此次实机策略冻结导入，不能将旧桥接的 Arm G + MCTS 当作目标策略。

## 缺少哪些字段

每条游戏 RNG 需要 `counter`、内部状态 `seed0`、`seed1`，并在流未初始化时保留明确的初始化标记。内部两字状态与开局种子是不同概念。

| 随机源 | 当前 Steam 导出 | 本次 oracle 导出 | 需要补充的工作 |
|---|---|---|---|
| `aiRng`、`cardRandomRng`、`miscRng`、`monsterHpRng`、`potionRng`、`shuffleRng` | 6 条，含三字段 | 6 条，含三字段 | 保留状态导入与动作后比较；测试 SL 前后恢复 |
| `monsterRng`、`mapRng`、`eventRng`、`merchantRng`、`cardRng`、`treasureRng`、`relicRng` | 缺失，共 21 个数值字段；局外也无导出入口 | 7 条，含三字段 | 接入全局导出与对应的局外状态导入 |
| `NeowEvent.rng` | 缺失 | 缺失 | 补 `counter`、`seed0`、`seed1` 与初始化标记；覆盖涅奥奖励生成前后 |
| `MathUtils.random` | 缺失 | 读到 `seed0`、`seed1` | 明确实际类型、初始化状态、规则与动画消费来源；没有游戏 `counter`，不能伪造计数 |
| `java.util.Collections.r` | 缺失 | 读到 `initialized`、`seed48` | 记录 Java 随机源与作用路径，确定模拟器预测及 SL 对它的处理 |

本机 JAR 的字段扫描还列出了每日挑战界面 RNG 与 RNG 包装对象内部的 `random` 字段；前者不属于本次自然普通开局，后者不应重复算作一条独立游戏流。扫描范围是原版 `com/megacrit` 类的声明字段，不是所有方法局部变量、运行时 Mod 或第三方库单例的穷举证明。

`AlignmentProbe.view()` 通过遍历 `AbstractDungeon.class.getFields()` 导出地牢 RNG，因此不会包含属于 `NeowEvent` 的静态字段。这一遗漏有字节码声明、采集源码和运行响应三种证据。

## 能否用读档或重放推断

原版进房间时，将 `monsterHpRng`、`aiRng`、`shuffleRng`、`cardRandomRng`、`miscRng` 设为 `Settings.seed + floorNum`。因此，固定进入状态并重放相同随机调用序列，具有恢复这些流的依据。存档保存怪物、事件、商店、卡牌、宝箱、遗物、药水等流的调用计数，加载时按开局种子与计数恢复其中的流。

但存档计数不是任意战斗中间状态的完整快照。牌堆顺序、遗物与能力状态、动作队列、候选牌以及生成物身份也会改变后续随机调用。完整内部状态的读取比猜测调用次数更合适。`NeowEvent.rng` 由开局种子初始化，理论上可以重放其生成步骤推算；读取原字段成本更低，仍须用原版响应核对。

`SaveFile` 没有保存 `MathUtils.random` 与 `Collections.r` 的完整状态，原版 `loadSeeds` 也没有恢复它们。普通 SL 无法作为这两个源恢复一致的保证。确定性重放若要覆盖它们，需要记录并恢复来源状态，还要复现消费过程；仅记录种子、楼层和玩家操作不足以作出这一保证。

另一个边界来自运行时 Mod：原版 `DiscardAtEndOfTurnAction` 调用不带种子的 `Collections.shuffle(cards)`；本机 BaseMod 含 `ConsistentEtherealPatch`，会把这一处换成由游戏种子、楼层、回合生成的随机源。本次实例 `BaseMod.fixesEnabled=true`。这会改变参考规则；采用它得到的确定性不能归因于未经该补丁的原版。此前 parity 工具支持在隔离副本中去掉这一处补丁，但本次没有启用该诊断配置。

以上 SL 说明来自本机源码与字节码检查，**本次实测没有验证读档后轨迹一致**。没有据此宣称某张牌已导致胜负变化。

## 交付证据与入口

所有路径相对于本工作树：

| 文件 | 用途 |
|---|---|
| `docs/live-original-source-manifest.json` | 基线、导入来源与 SHA-256；记录来自 parity 未提交目录的代码 |
| `steam/rng_preflight.py` | 有限原版采集与离线审计入口 |
| `docs/live-original-runbook.md` | 运行命令、退出码、日志读取和下一阶段验收要求 |
| `runs/rng-preflight-20260927-installed/audit-summary.json` | 根据原始响应重新计算的缺口结论；作为本报告的机器可读摘要 |
| `runs/rng-preflight-20260927-installed/original/rpc.jsonl` | 每次请求与响应，含当时能够导出的状态 |
| `runs/rng-preflight-20260927-installed/original/observations.json.gz` | 压缩观察记录，SHA-256 `97862859770471232d8f1d33e57c5b789899488fd4849eaad0857040890c94f4` |
| `runs/rng-preflight-20260927-installed/first-combat.json`、`after-first-end.json` | 首战前后观察点 |
| `runs/rng-preflight-20260927-installed/original/identity.json` | 原版 JAR、所有 Mod、启用列表、探针与外部辅助代码哈希 |
| `runs/rng-preflight-20260927-installed/original/cleanup.json` | 所有自有原版进程的退出结果 |
| `runs/rng-preflight-20260927-installed/capture-sources/rng_preflight.py` | 此次采集时执行的脚本版本；后续改动限于审计和报告逻辑 |
| `runs/rng-preflight-static-20260927/inventory.json`、`*.javap.txt` | 本机 JAR 字段扫描、字节码以及对应本地源码哈希 |

日志支持浏览原始状态、提取命令和重新执行命令；**完整确定性重放尚未验收**。没有完整局录像。原版 JAR 位于 Git 忽略的本地运行目录，没有提交、推送或分发。

## 剩余任务与下一步决定

| 原请求 | 本次状态 |
|---|---|
| 目标策略接入与每步状态/RNG 对比 | RNG 前置检查完成；完整接入没有实施 |
| 分歧后重同步、重规划、按需 SL | 没有实施；先确定完整导出和恢复契约 |
| 至少 20 局、胜局、每局分歧、SL 统计 | 完成整局 0；没有胜率和逐局统计 |
| 出现频率 × 胜负影响排序 | 无评测分母、无胜负反事实证据，不计算排名 |
| 高影响规则补丁与价值表重测清单 | 没有新增规则修复，也没有得到经验证的牌/怪物条目重测清单 |

建议继续的有界步骤是：补齐全局 RNG 导出（包含涅奥和共享源），绑定运行时 Mod 配置，在涅奥、首战、一次重洗和一次 SL 四个位置验收。对共享源，区分导出成功、模拟器能导入、原版重放能恢复三件事。只有通过这些检查，才冻结 P300 父网络、价值表和搜索运行时，实施完整状态桥接并启动 20 局。

若决定继续，可将 `5100000000` 保留为开发种子，评测预注册为 `5100000100` 至 `5100000119`，避免把本次观察当作新种子评测。这个种子安排是建议，本次没有启动该批次。

此次停止依据是用户任务中的原文：“若 mod 无法导出完整 RNG 状态，先报告缺哪些字段、能否用读档/重放推断，再决定是否继续；不要在未确认可行前做大量工程。” 本报告中的“缺失”指现有实现与已验证契约，不表示这些字段无法通过扩展 Mod 导出。
