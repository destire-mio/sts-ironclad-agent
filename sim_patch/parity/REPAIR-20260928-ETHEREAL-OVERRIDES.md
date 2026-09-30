# 2026-09-28 虚无牌特殊回调与免费状态修复

沿着上一轮的回合结束规则检查，发现巩固和幽灵铠甲覆盖了通用回调：它们把 `ExhaustAllEtherealAction` 放入队首。这个动作在执行时读取当前手牌，再为每张虚无牌排入指定牌消耗动作。旧模拟器只按 `isEthereal` 处理，漏掉了巩固的回调，也把幽灵铠甲当成普通虚无牌。

以手牌“晕眩、进阶之灾、灵体、巩固”为例，原版消耗顺序为“灵体、进阶之灾、晕眩”，上一版模拟器的顺序不同。新增 8 个原版场景包含两种卡牌、不同手牌位置、黑暗之拥／无惧疼痛／枯木、共享 Java RNG 和两个对照，旧版出现 4 个差异。

追查消耗动作时还发现免费状态残留。用深谋远虑让幽灵铠甲或残杀下次免费，抽到后不打出，等待虚无消耗：原版 `ExhaustSpecificCardAction` 在消耗回调和移牌之后清掉 `freeToPlayOnce`，模拟器没有清除。3 个补充原版场景证实这两个差异，普通打击的弃牌对照保留免费状态。

[补丁](../ethereal_overrides.patch)接在 `ethereal_profiles.patch` 后。它在洗牌后的回调分派中补齐这两张牌的动作，动作执行时访问所属分支的手牌；重复排入的指定牌消耗遇到已移出的牌时返回；指定牌消耗完成后清除一次免费标志。改动位于 `BattleContext.cpp`，没有把所有移入消耗堆的动作改成同一种状态清理。源码哈希和应用顺序见[分发清单](../alignment/ethereal-overrides-manifest.json)。

上一轮 C++ 通用洗牌夹具使用了幽灵铠甲，其期望只来自 Java 洗牌结果，遗漏卡牌的特殊回调。这轮将通用夹具改用灵体，并增加独立原版的特殊回调验收；前一轮产物和原版捕获保留。这个遗漏说明通用算法通过不能证明每张卡的回调正确。

| 检查 | 结果 |
|---|---|
| 11 个不可变原版场景 | 旧生产／观察各 6 个差异、5 个吻合；新生产／观察被比较字段吻合，均保留 `coverage_gap` |
| 10 组 C++ 回归 | 旧版 5 失败、5 通过；新版 10 通过，包含动作执行时手牌、队列复制、重复回调、保留牌、金字塔、免费状态与取回后的出牌条件 |
| CTest | 一次完整运行，366 个入口通过 |
| 累计原版验收 | 生产与观察构建各 31 项通过，覆盖 97 个原版场景及专项状态核对 |
| 搜索模块 | 重编后 8 次战斗通过单次／批量 1、4 线程一致性及输入状态、分支隔离检查 |
| 补丁与清理 | 性能版、E121 应用及改动编译单元检查通过；本轮 11 个采集 JVM 退出 |

- [运行时](../../runs/parity-repair-20260928-ethereal-overrides/runtime.json)、[源码核对](../../runs/parity-repair-20260928-ethereal-overrides/source-audit.json)、[交付核对](../../runs/parity-repair-20260928-ethereal-overrides/verification.json)
- [生产回放](../../runs/parity-repair-20260928-ethereal-overrides/replay-production/report.json)、[观察回放](../../runs/parity-repair-20260928-ethereal-overrides/replay-audit/report.json)、[原版来源](tests/fixtures/provenance.json)
- [C++ 回归](../alignment/tests/ethereal_overrides.cpp)、[原版验收](../alignment/tests/test_ethereal_overrides_original.py)、[前后回归](../../runs/parity-repair-20260928-ethereal-overrides/focused-before-after.json)、[CTest 日志](../../runs/parity-repair-20260928-ethereal-overrides/ctest.log)

同轮排查的战斗外原始差异与深度 2 动作树见[后续检查记录](RESULTS-20260928-ROUND11-OUTSIDE-TREE.md)。消耗堆费用重置的候选经 3 个原版场景排除：原版在 `ExhaustCardEffect` 动画完成时重置属性，稳定观察点与模拟器吻合；这些排查场景不计入 97 个修复验收场景。范围之外的共享随机消费、私有状态与动态分支缺口保留。完整一致性为 `INCOMPLETE`，goal 为 active；修改位于隔离 worktree，没有提交或推送。
