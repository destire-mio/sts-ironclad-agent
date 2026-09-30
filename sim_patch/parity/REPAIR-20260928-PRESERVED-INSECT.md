# 昆虫标本不能抬高涅奥压低的生命

原版确认：先持有涅奥的哀嚎、后获得昆虫标本，带着哀嚎次数进入精英战斗时，怪物开局应为 1 血。修复前模拟器把怪物改成最大生命的 75%。一个原版场景中，大块头最大生命 85，原版开局 1 血，模拟器开局 63 血；打击之后，原版进入胜利结算、玩家由 40 回到 46 血，旧模拟器中的怪物剩 57 血，战斗没有结束。

`PreservedInsect.atBattleStart` 只在当前生命高于 75% 上限时降血。`NeowsLament.atBattleStart` 把生命改成 1。native 的昆虫标本分支无条件赋值，覆盖了前一个遗物的结果。[源码依据](../../runs/parity-repair-20260928-preserved-insect/source-audit.json)绑定原版 Java 与前后 native 文件哈希。

[preserved_insect.patch](../preserved_insect.patch) 接在 `astrolabe_small.patch` 后，只修改 `BattleContext.cpp` 的一处规则：当前生命与标本上限取较小值。遗物遍历顺序、随机消耗与其他战前效果沿用原实现。[分发清单](../alignment/preserved-insect-manifest.json)记录输入、输出与补丁哈希。两份 portable 源码零模糊应用和语法检查通过，生产、观察及搜索模块在新目录构建；旧运行时作为基线保留。

| 验证 | 结果与边界 |
|---|---|
| 8 个独立原版 JVM 场景 | 修复前 3 个反例、5 个对照；生产和观察构建的比较字段在修复后吻合。含大块头、乐加维林、相反遗物顺序、哀嚎用尽、单个遗物和普通敌人，并执行一次打击 |
| 8 个 native 定向入口 | 同一测试文件链接旧核心得到 4 失败、4 通过；新核心 8 通过。含三只哨卫、事件精英、非精英及复制分支中的攻击隔离 |
| 完整回归 | 411 个 CTest 入口通过；生产、观察构建各通过 42 项累计原版验收，覆盖 182 个场景及状态合同；检查器 41 项通过 |
| 自然轨迹 | 不可变历史输入的 1002 条命令重放；第 51 层失败终局，分数 1786。该轨迹不构成自然胜率结果 |
| 历史战斗外样本 | 914 条完整比较步骤与旧运行时相同：597 个 `coverage_gap`、317 个 `observation_difference`。没有消去遗物原始计数或旧阶段差异来制造通过 |
| 搜索模块 | 8 个战斗的单条／批量结果吻合；输入状态、RNG 和复制隔离检查通过。不含性能或策略收益声明 |

[原版输入](tests/fixtures/preserved-insect-original.json.gz)、[来源清单](tests/fixtures/provenance.json)、[修复前后分类](../../runs/parity-repair-20260928-preserved-insect/classification.json)、[定向前后结果](../../runs/parity-repair-20260928-preserved-insect/focused-before-after.json)、[回归日志](../../runs/parity-repair-20260928-preserved-insect/ctest.log)、[914 条刷新](../../runs/parity-repair-20260928-preserved-insect/existing-outside-comparison.json)。

本轮补足了 [40 个事件及 7 个存档入战场景](RESULTS-20260928-EVENT-SAVE-ENTRY.md)的输入和观察阶段配对。这 47 个场景也计入上述累计合同。55 个原版实例均停止，[清理证据](../../runs/parity-repair-20260928-preserved-insect/original-cleanup.json)保留实例身份。

运行时入口：[runtime.json](../../runs/parity-repair-20260928-preserved-insect/runtime.json)。可复查核验脚本：[verify_delivery.py](../../runs/parity-repair-20260928-preserved-insect/verify_delivery.py)，输出 [verification.json](../../runs/parity-repair-20260928-preserved-insect/verification.json)。

原版参照为本地安装 Mod 的隔离逻辑运行时，不是无 Mod 原版。全私有状态、全部遗物计数、事件奖励后续行为和无界动作序列未覆盖。goal 保持 active；[下一组计数生命周期问题](../../runs/parity-repair-20260928-preserved-insect/next-counter-audit.json)与[持续清单](CONTINUOUS-AUDIT.md)保留待核实事项，没有提交或推送。
