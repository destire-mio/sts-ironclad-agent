# 2026-09-28 群攻与鸟面瓮修复

本轮修复[第五轮检查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/RESULTS-20260928-ROUND5.md)中的两类规则差异：群攻读取力量的时点，以及鸟面瓮回血与疼痛失血的顺序。工作位于隔离 worktree `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`。12 个原版场景的被比较字段吻合，293 个 CTest 入口通过。全量一致性验收为 `INCOMPLETE`；其他历史差异不在本次修复范围内。

## 改动

群攻在出牌时计算并保存各敌人的伤害。顺劈斩、戏剧性开场、燔祭、死亡收割、闪电霹雳和旋风斩共用这条路径，后续疼痛失血触发的力量不回写当前牌的伤害。伤害动作按值携带数组，执行时使用所属战斗分支的敌人、格挡和生命；死亡收割按该分支敌人的实际生命损失回血。

实现增加 [`calculateCardDamageMatrix`](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/source/src/combat/BattleContext.cpp:2682)，移除延迟读取当前牌和力量的动作重载。原先加进基础伤害、用于弥补延迟结算时活力消失的代码被删除，活力由现有伤害公式计算一次。数组使用 `int`，与现有伤害计算的返回类型一致，避免将单次群攻的整型伤害存入 16 位数组时引入截断。

鸟面瓮在出牌回调中将 [`HealPlayer(2)` 放到队首](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/source/src/combat/BattleContext.cpp:1880)。随后疼痛把失血动作插到它前面，形成原版的失血、回血次序。复用的回血动作读取执行分支的玩家状态，保留生命上限、魔法花和绽放印记处理，以及战斗胜利后的回血动作保留规则。

补丁改动四个规则文件：`Actions.h`、`BattleContext.h`、`Actions.cpp`、`BattleContext.cpp`。原有疼痛／虚空修复保留；旧源码和旧运行时保留，原版样本没有改写。

## 同一输入的修复前后结果

以下群攻场景以 50 生命、3 能量开始，依次打出撕裂和表中的攻击，手中保留疼痛。敌人为夹具设置的 300 生命邪教徒，用于避免终局打断比较，这不是自然生成的敌人生命。旋风斩使用打出撕裂后剩余的 2 能量。

| 卡牌 | 原版伤害 | 修复前伤害 | 修复后伤害 |
|---|---:|---:|---:|
| 顺劈斩 | 8 | 9 | 8 |
| 死亡收割 | 4 | 5 | 4 |
| 戏剧性开场 | 8 | 9 | 8 |
| 燔祭 | 21 | 22 | 21 |
| 闪电霹雳 | 4 | 5 | 4 |
| 旋风斩 | 10 | 12 | 10 |

死亡收割结算后的玩家生命由修复前的 53 变为 52，与原版吻合。鸟面瓮场景的生命上限为 80：起始 80 或 79 生命时，原版与修复版的结果为 80，修复前为 79。无疼痛、使用愤怒和受伤状态下的鸟面瓮对照保留吻合结果。

本次验收复用第五轮 8 个原版场景，并为其余四种群攻捕获 4 个新场景。每个新场景使用独立原版 JVM 与存档副本，在修复前引擎上复现差异。12 个场景在修复前包含 8 个反例、4 个对照；修复后全部被比较字段吻合，分类为 12 个 `coverage_gap`，覆盖缺口没有转换成通过声明。

- [第五轮群攻样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/pain-aoe-original.json.gz)、[鸟面瓮样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/urn-pain-original.json.gz)
- [补充场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/aoe_urn_repair_controls.json)、[补充原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/aoe-urn-repair-original.json.gz)、[修复前捕获报告](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/original-extended/report.json)
- [来源清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)保存文件及记录哈希、游戏与运行时 Mod 身份。队列次序解释所用的 15 个原版源码文件身份见[源码核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/source-audit.json)。

## 验证

| 检查 | 结果与范围 |
|---|---|
| 原版样本验收 | 12 个场景在生产构建和观察构建中吻合；起点导入一次，后续没有重同步 |
| 原生边界检查 | 8 组通过；修复前 5 组失败、3 组对照通过 |
| 完整 CTest | 293 个入口通过，无失败或跳过，包含本轮 8 个原生入口及原版样本验收入口 |
| 观察构建验收 | 5 项 Python 测试通过，覆盖本轮 12 个场景和上轮疼痛／虚空的 8 个场景 |
| 冻结检查器回归 | 41 项通过，旧差异检测预期保留 |
| 训练模块 | 重建 `slaythespire` 与 `fightsim`；8 次战斗的单次／批量结果吻合，输入状态、随机数及复制隔离检查通过 |
| 补丁分发 | 性能优化版与归档 E121 加疼痛／虚空补丁后均可应用；两个修改的 C++ 编译单元通过语法编译检查 |
| 原版进程 | 4 个新增原版实例完成清理，剩余进程列表为空 |

[原生检查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/tests/aoe_urn_order.cpp)覆盖六种群攻及升级版本、力量／活力／笔尖／虚弱／易伤／格挡组合、等待结算动作的分支复制、整型伤害范围、鸟面瓮与致命疼痛、绽放印记，以及死亡收割在终局后的实际伤害回血。高伤害与分支修改是原生构造边界，不是自然原版对局证据。

[原版验收测试](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/tests/test_aoe_urn_original.py)在旧引擎中得到 8 个失败子案例，在新引擎中通过。旧检测测试 `test_repaired_native.py` 针对上一版引擎，保持发现时的预期。

- [生产构建回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/replay-production/report.json)、[观察构建回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/replay-audit/report.json)
- [完整回归日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/ctest.log)、[观察构建验收日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/audit-original-tests.log)、[冻结检查器日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/checker-frozen-tests.log)
- [修复前原版验收失败](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/baseline-original-tests.log)、[修复前原生结果](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/baseline-native-results.json)、[训练模块检查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/runtime-smoke.json)
- [补丁应用与编译核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/portable-patch-verification.json)、[原版实例清理](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/original-cleanup.json)、[交付核查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/verification.json)

首轮分发核对中，`git apply` 在嵌套的未跟踪源码目录中返回成功但跳过文件，后续源码哈希检查拒绝了该结果。重建副本后改用 `patch -p1`，逐文件核对改动并通过编译；[初次失败记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/portable-initial-failure.json)保留。归档 E121 的编译检查不等于该版本的运行时验收；完整运行与回归基于本次性能优化版源码。

## 使用入口与边界

[分发补丁](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/aoe_urn_order.patch)接在 `pain_void_order.patch` 后应用，文件身份和适用版本见[分发清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/aoe-urn-order-manifest.json)。接口和动作中的数据类型发生变化，核心、搜索和绑定需要一起重编。

本机修复版位于 [runs/parity-repair-20260928/build](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/build)，包含 `slaythespire` 和 `fightsim`。[运行时清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928/runtime.json)记录二进制、源码及构建输入哈希。观察构建位于同级 `audit/build`。旧运行时目录保留，使用旧路径的实验不会因本次本地修复切换引擎。

原版对照为游戏 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的隔离逻辑运行时。验收覆盖本报告的受控输入和现有回归，不构成无 Mod 原版、自然整局或所有可达状态的一致性证明，也不提供速度或胜率结论。改动保留在隔离 worktree，没有提交或推送。
