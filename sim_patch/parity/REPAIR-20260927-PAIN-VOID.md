# 疼痛与虚空规则修复

修复第四轮检查确认的两处规则差异：疼痛失血触发撕裂，以及虚空抽到后的扣能量顺序。补丁和重建运行时位于隔离 worktree `sts-rl-agent-parity`，分支为 `codex/original-simulator-parity-20260927`。代码处于待提交、待推送状态；全量原版一致性为 `INCOMPLETE`。

## 改动与结果

[`pain_void_order.patch`](../pain_void_order.patch) 修改两个规则位置：

- 疼痛调用 `PlayerLoseHp(1, true)`，将失血来源标记为玩家。撕裂复用现有失血回调增加力量，钨合金棍挡住失血时保持零触发。
- 虚空把扣能量动作追加到队列末尾，结算时减去 1 并截断到 0。回调读取执行分支传入的 `BattleContext`，没有捕获原分支引用。动作沿用战斗胜利时清理的默认标记，与原版 `LoseEnergyAction` 的清理规则对应。

使用[第四轮原版记录](RESULTS-20260927-ROUND4.md)中的同一批输入、命令和观察值进行回放，没有修改原版样本，也没有在中途重新导入原版状态。

| 受控场景 | 原版 | 修复前 | 修复后 |
|---|---:|---:|---:|
| 普通撕裂：两张愤怒结算后的力量／敌人生命 | 2／287 | 0／288 | 2／287 |
| 升级撕裂：两张愤怒结算后的力量／敌人生命 | 4／286 | 0／288 | 4／286 |
| 0 能量、符文立方体、祭品抽到虚空：最终能量 | 1 | 2 | 1 |
| 0 能量、符文立方体、放血抽到虚空：最终能量 | 1 | 2 | 1 |

另外四个对照为放血触发撕裂、疼痛但无撕裂、祭品但无符文立方体、初始 1 能量的虚空场景。修复前后，对照的被比较字段均与原版记录吻合。8 个场景在修复后的普通构建和观察构建中得到相同的回放结果；`coverage_gap` 保留，表示检查器存在尚未映射的状态或覆盖义务，不能改写为完整一致性通过。

## 验证

- **修复前失败**：新原版验收测试在冻结旧引擎上检出 4 个反例失败；4 个对照通过。新增 C++ 边界测试在旧引擎上有 2 个失败，分别是待执行虚空动作的分支复制、喷火击杀后待扣能量动作的清理。
- **原版样本验收**：修复后的两种构建各回放 8 个场景，被比较字段吻合。原版样本文件与上轮来源哈希相同；没有用新模拟器输出生成期望值。
- **原生与集成回归**：283 项 CTest 套件通过；随后注册的原版样本入口包含 2 个 Python 测试、8 个场景，在独立进程中通过。合计 284 个注册入口通过，无跳过。283 项套件包含新增的钨合金棍、分支复制、喷火击杀和存活对照。
- **检查器回归**：41 项测试在冻结基线上通过，保留检测已知差异的能力。这与修复版的验收入口分开运行，避免同一 Python 进程混用两个同名 native 模块。
- **训练模块接入**：`slaythespire` 和 `fightsim` 从修复后的核心重建，8 次战斗的单次／批量结果相同，输入状态、随机数和副本隔离检查通过。这项检查不提供吞吐率或胜率结论。
- **补丁分发**：补丁在性能优化版和归档 E121 源码副本上应用通过；性能优化版应用后的两个文件与被测源码逐字节相同。冻结的输入源码保留原哈希。

分发复核把入队表达式改为显式构造 `Action`，兼容 E121 的非模板构造接口。最终写法的两个修改文件通过 E121 头文件下的 C++17 编译检查；这不是一份 E121 完整运行时验收。性能优化版重建后的 `CardManager` 目标文件和普通 native 模块与通过上述回归的候选逐字节相同，最终 5 个 `pain_void_*` 入口复跑通过。最终观察构建重建后，8 个原版场景回放吻合。

原版依据为上轮独立 JVM 捕获及 Java 源码。上轮运行时包含 BaseMod、CommunicationMod、SpireLabLogic 等 Mod；本轮回放既有原版记录，没有产生新的无 Mod 原版整局证据。其他已知差异、所有私有状态、完整输入域、自然对局触发率和胜率影响保留为待验证范围。

## 使用入口

可分发文件为[补丁](../pain_void_order.patch)、[源码身份清单](../alignment/pain-void-order-manifest.json)、[原版验收测试](../alignment/tests/test_pain_void_original.py)和[原生边界测试](../alignment/tests/pain_void_order.cpp)。补丁接在 `e121_power_order.patch` 后应用，要求重编核心、搜索与绑定；现有性能优化版可应用同一补丁。CMake 入口为 `sim_patch/alignment`，运行 `ctest` 会包含新增验收。

本机修复版运行时位于：

```sh
export STS_LIGHTSPEED_BUILD=/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/build
```

该目录包含 `slaythespire` 与 `fightsim`；[运行时清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/runtime.json)记录模块哈希、源码身份和构建输入。观察构建位于同级 `audit-final/build`，用于输出额外比较字段。旧冻结引擎没有覆盖，使用旧路径的实验需要在新实验配置中选择这个修复版目录；历史训练标签保留其原引擎身份。

复跑原版样本验收：

```sh
PARITY_REPAIRED_ENGINE="$STS_LIGHTSPEED_BUILD" \
  /Users/destire/Documents/Codex/2026-09-10/new-chat-2/outputs/spire-lab/.venv/bin/python \
  /Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/tests/test_pain_void_original.py -v
```

## 本机证据

- [交付核查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/verification.json)与[补丁应用核查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/portable-patch-verification.json)
- [普通构建疼痛回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/replay-production-pain-rupture/report.json)、[虚空回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/replay-production-void-energy/report.json)
- [观察构建疼痛回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/replay-audit-final-pain-rupture/report.json)、[虚空回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/replay-audit-final-void-energy/report.json)
- [283 项套件日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/ctest.log)、[新增原版验收入口日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/ctest-original-contract.log)、[41 项检查器测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/checker-baseline-tests.log)
- [旧引擎原版反例失败日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/baseline-repair-tests-final.log)、[旧引擎边界结果](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/baseline-native-results.json)、[训练模块调用检查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/runtime-smoke.json)
- [最终 5 个针对性入口](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/ctest-final-focused.log)、[重建前后模块比较](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/explicit-action-binary-comparison.json)、[E121 修改文件编译日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260927/e121-final-compile.log)
