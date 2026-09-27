# 原版持久 RNG 导出修复

修复对象：自然普通开局中的 13 条地牢 RNG、`NeowEvent.rng`、`MathUtils.random` 和 `Collections.r`。本次解决已知的持久 RNG 导出缺口，尚未完成 20 局实机评测或 SL 整局状态恢复。

## 行为变化

此前 `getCombatState` 只导出 6 条战斗 RNG，涅奥、地图等局外屏幕缺少完整导出。现在 `GameRngPatch` 在 `GameStateConverter.getGameState` 的返回值中加入 `full_rng_state`，覆盖战斗和局外决策。13 条地牢 RNG 通过原版字段枚举读取，涅奥与两个共享源有独立条目。

RNG 未初始化时记录 `initialized:false`，不替它创建随机源。64 位状态和 Gaussian 缓存的原始 double 位使用十进制字符串。游戏 RNG 保留原版调用计数；共享源没有相应计数，不填造一个 `counter`。Java 的 `nextGaussian()` 缓存也会影响下一次输出，因此一并读取。未知随机源子类、反射失败或不完整状态产生 `complete:false` 与错误内容。

旧 `combat_state.rngs` 仍为 6 条，避免新格式破坏现有 `BattleContext` 入口。Python 契约检查逐观察点验证全部 16 条流，核对独立 oracle 的状态位及旧接口。一个观察点缺字段，不能借另一观察点的数据判定通过。

## 原版验证

使用种子 `5100000000` / `2S3KFAQ`，执行与修复前相同的 6 条命令：自然 A20 Ironclad 开局、4 次 `choose 0`、结束首战第 1 回合。首战为 `SpikeSlime_S` 与 `AcidSlime_M`。本次记录包含涅奥、地图、首战和第 2 回合，共 7 个游戏内观察点。

| 检查 | 结果与适用范围 |
|---|---|
| 16 条持久 RNG 导出 | 7 个观察点通过格式与独立原版读取核对 |
| 涅奥生命周期 | 第一个观察点为未初始化，后续观察点记录真实状态，没有虚构初始种子 |
| 原有地牢 RNG | 修复前后的同种子、同输入，7 个位置的 13 条流状态逐项相同 |
| 观察副作用 | 稳定决策点重复观察的 RNG 相同；合法动作观察前后字段相同 |
| 原版后续随机数 | 16 个随机源 + 1 个带 Gaussian 缓存的控制，共 17 组通过；每组 120 次后续输出核对 |
| 回滚诊断采样 | 诊断结束后，16 条持久随机源的导出快照与采样前相同 |
| 回归夹具 | 修复前缺失导出被拒绝；修复后前缀通过。覆盖字段缺失、浮点精度、独立读取分歧、未知类型、缓存与初始化状态 |
| Java 构建 | 采集用 ECJ/Java 8 编译通过；独立 SteamStateExport JAR 构建通过，保留原有 Java 编译警告 |
| 进程清理 | 本次隔离原版进程退出，`cleanup.json` 的 `remaining` 为空 |

原版 JAR SHA-256：`dd60a613a6178e08f1a57bcb8d5747e33c21fd49e743b88d76e9d74042803b2a`。游戏 JAR 与 BaseMod 与本机安装哈希一致。运行时为原有固定帧 Java 逻辑采集实例，含 BaseMod、CommunicationMod、SpireLabObserver、SpireLabLogic 与探针；不将它宣称为 Steam 图形界面整局验收或无 Mod 原版等价性证明。

随机数验证在独立诊断实例中执行：先从待测导出创建副本，再比较副本与原版对象的后续结果；回滚使用独立保存的原始字段，不使用待测导出，避免错误导出污染原对象。此过程验证的是随机源重建，不是整场战斗存档读取。

## 证据与复现

- `steam/rng_preflight.py --roundtrip`：采集及原版后续随机数核对，完整命令见 `docs/live-original-runbook.md`。
- `runs/rng-fix-20260927-v1/result.json`：导出契约与重复观察结果。
- `runs/rng-fix-20260927-v1/rng-roundtrip.json`：17 组原版预期/实际输出，以及采样前后 RNG 状态。
- `runs/rng-fix-20260927-v1/original/observations.json.gz`：原始动作/响应记录。
- `runs/rng-fix-20260927-v1/original/identity.json`：JAR、Mod、启用列表、实际编译的源文件与外部辅助代码哈希。
- `steam/tests/fixtures/original-rng-prefix.json.gz`：适合入库的原版修复前后 RNG 数值夹具。
- `steam/tests/fixtures/provenance.json`、`docs/live-original-source-manifest.json`：夹具和导入来源哈希。

源代码、文档与数值夹具可以提交。原版 JAR、反编译源码、存档、完整本地运行目录和构建产物维持 Git 忽略，不随此修复分发。`sts-rl-agent-principles` 没有作为写入目标，用户原有实验进程没有被停止。

## 适用边界

“完整”限于列出的 16 个持久自然开局随机源，不包括每日挑战或第三方 Mod 新增 RNG，也不是对所有方法局部对象、动画与规则消费顺序的穷举证明。BaseMod 的虚无牌洗牌补丁仍是参考运行环境的一部分。

当前 `steam_mcts.py` 继续通过旧接口接收 6 条战斗 RNG。导出修复没有实现其他随机源的模拟器导入，也没有接入 P300 指定 arm、分歧重规划或自动 SL。普通存档没有保存两个共享源的状态，这一恢复边界没有因新增导出而消失。

20 局评测完成数为 0，胜率与分歧胜负影响没有测量。本次没有修改模拟器规则或价值表，因此没有新增经验证的牌/怪物重测条目。后续工作从真实状态导入与保存恢复链路继续查找，不以本次导出通过替代整局验收。
