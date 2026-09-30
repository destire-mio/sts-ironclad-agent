# 2026-09-28 虚无牌消耗顺序与共享随机状态修复

旧模拟器按手牌倒序消耗虚无牌。原版 `DiscardAtEndOfTurnAction` 先取出保留牌，再打乱其余手牌的副本，按回调顺序把消耗动作放入队首。普通牌也参与这次洗牌，实际手牌顺序不变。消耗先后会影响消耗堆、枯木生成牌和黑暗之拥抽牌。

本地安装的 BaseMod 又改变了这条规则：它使用“游戏种子 + 楼层 × 55 + 原版回合数”创建局部 Java 随机源；移除 `ConsistentEtherealPatch` 的两个类后，执行游戏原有的 `Collections` 共享随机源路径。此次分别捕获两种配置各 4 个场景，保留 Mod 与原版 JAR 身份，未修改用户安装。[来源清单](tests/fixtures/provenance.json)中的 `round11_ethereal_profiles_original_identities` 可核对差别。

实现把配置和共享 Java 随机状态作为战斗状态保存。生产快照导出器读取原版字段，导入器验证模式、初始化标志与 48 位种子；模拟器在动作执行中推进状态，搜索分支持有自己的副本，战后传回整局状态。没有中途用原版状态覆盖模拟器。项目默认配置对应当前安装的 BaseMod；旧快照缺少配置时保留覆盖缺口，未初始化的共享随机源不能被猜成固定种子。

同时修正按牌身份寻找待消耗牌的循环：旧代码循环遍历 `i`，却检查 `hand[idx]`。前一张牌移出手牌后，它可能漏牌或移除另一张牌。新代码按当前下标与唯一标识查找，支持打乱后的消耗次序。[补丁](../ethereal_profiles.patch)接在 `colosseum_enrage.patch` 后；结构布局变化要求重编核心、搜索和绑定。[分发清单](../alignment/ethereal-profiles-manifest.json)记录前后源码哈希。

| 原版配置与场景 | 修复前 | 修复后 |
|---|---|---|
| BaseMod：3 张虚无牌、混合手牌、金字塔连续两回合、消耗效果组合 | 4 个差异 | 4 个场景被比较字段吻合 |
| 共享 Java RNG：3 张虚无牌、混合手牌、金字塔连续两回合、无虚无牌对照 | 2 个差异、2 个吻合；共享状态未映射 | 4 个场景被比较字段和共享状态吻合 |

无虚无牌对照中，原版共享随机状态从 `99420211257010` 变为 `137691661925845`，下一回合变为 `262397244341387`。新模拟器复现这两个变化，说明可见的消耗堆为空不能替代随机状态检查。篡改记录中的一个随机状态位会触发比较失败。

| 检查 | 结果 |
|---|---|
| 原版不可变捕获 | 8 个场景，旧生产／观察各 6 个差异；新生产／观察被比较字段吻合，均保留 `coverage_gap` |
| C++ 行为回归 | 5 组可在旧接口运行：旧版 2 失败、3 通过；新版 11 组通过，包括身份偏移、保留牌、金字塔、队列复制、状态隔离与战后传递 |
| 独立 Java 对照 | 游戏 JRE 生成 77 个洗牌样本、49 组有界随机序列；比较值与最终状态，包含拒绝采样与边界种子 |
| CTest | 一次完整运行，355 个入口通过 |
| 累计原版验收 | 生产与观察构建各 27 项通过，覆盖 86 个原版场景及专项状态核对 |
| 检查器负例 | 冻结旧引擎上的 41 项通过，旧缺陷检测仍能失败 |
| 搜索与跨模块调用 | 8 次战斗，包含两种配置；单次／批量 1、4 线程结果吻合，输入状态与分支隔离通过 |
| 分发与清理 | 性能版、E121 补丁应用通过，各 4 个编译单元语法检查；8 个采集 JVM 退出 |

第一次构建遇到绑定命名空间冲突，修正为 `pybind11::dict` 后通过；两项新增测试的初稿缺少战后回调，补齐奖励流程和自然战斗入口后通过。失败日志保留，不能算作规则反例。

- [运行时](../../runs/parity-repair-20260928-ethereal-profiles/runtime.json)、[源码核对](../../runs/parity-repair-20260928-ethereal-profiles/source-audit.json)、[交付核对](../../runs/parity-repair-20260928-ethereal-profiles/verification.json)
- [生产回放](../../runs/parity-repair-20260928-ethereal-profiles/replay-production/report.json)、[观察回放](../../runs/parity-repair-20260928-ethereal-profiles/replay-audit/report.json)、[回归日志](../../runs/parity-repair-20260928-ethereal-profiles/ctest.log)
- [C++ 回归](../alignment/tests/ethereal_profiles.cpp)、[原版验收](../alignment/tests/test_ethereal_profiles_original.py)、[Java 对照程序](../alignment/tests/EndTurnShuffleReference.java)、[前后回归结果](../../runs/parity-repair-20260928-ethereal-profiles/focused-before-after.json)

参考环境仍含其他 Mod。共享随机源还用于原版地下城的无色牌池生成，本轮没有实现或证明无 Mod 整局的全部消费路径。私有状态、动态分支和自然胜率等覆盖缺口保留；完整一致性为 `INCOMPLETE`。goal 为 active，后续沿[持续排查清单](CONTINUOUS-AUDIT.md)检查战斗外差异与交互候选。修改位于隔离 worktree，没有提交或推送。
