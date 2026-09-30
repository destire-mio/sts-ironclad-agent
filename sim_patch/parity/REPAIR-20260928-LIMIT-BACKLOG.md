# 2026-09-28 突破极限与历史待办修复

本轮处理第九轮的突破极限，以及第一至三轮记录中的四项历史待办。五类修复在同一批 16 个原版记录上消除了 9 个首处分歧；7 个对照场景保持吻合。生产与观察构建的被比较字段吻合，未知字段保留 `coverage_gap`。完整一致性状态为 `INCOMPLETE`。

改动位于隔离 worktree `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`，没有提交或推送。生产构建为 `runs/parity-repair-20260928-limit-backlog/build`，观察构建为同级 `audit/build`。旧源码、构建及原版样本保持原有哈希。

| 修复 | 原因与结果 |
|---|---|
| 负力量突破极限与人工制品 | 原版排入负力量的 ApplyPower 动作，由人工制品抵挡；模拟器绕过减益入口。负 3 力量、1 层人工制品的结果从负 6／1 修正为负 3／0，普通与升级牌各一例 |
| 双发、复制药水叠加暴走 | 原版按同一 UUID 更新等待执行的副本。模拟器补上出牌队列中的同身份实例，普通暴走总伤害从 34 修正为 39，升级牌从 40 修正为 48；另一张暴走不受影响 |
| 带壳寄生怪致命吸血 | 保存的实际扣血量以受击前生命封顶，复活后的生命不参与计算。玩家受击前 5 生命、伤害 12 时，怪物从 20 回到 25，旧版回到 32 |
| 旋风斩与精致折扇 | 旋风斩把各段攻击加入队尾，出牌触发的格挡先于攻击结算。三能量荆棘场景玩家剩 33 生命，旧版为 29 生命并残留 4 格挡 |
| 赌徒药水弃牌计数 | 每张手动弃牌增加当回合弃牌计数；弃 4 张后从 0 修正为 4，下回合复位 |

暴走的第九轮单复制对照不能排除第二轮的两种复制效果叠加问题。两组原版样本名称分别为 `rampage-copy-original` 和 `rampage-copies-original`，含义不同。

实现见 [补丁](../limit_backlog_rules.patch)与[分发清单](../alignment/limit-backlog-rules-manifest.json)。补丁接在 `rupture_brutality_order.patch` 后，重编核心、搜索和绑定。删除旋风斩专用递归攻击辅助函数，复用现有动作队列；没有添加运行时开关或回填原版结果。原版依据及文件哈希记录在[源码核对](../../runs/parity-repair-20260928-limit-backlog/source-audit.json)。

| 验证 | 结果 |
|---|---|
| 16 个原版记录重放 | 修复前 9 个 `mismatch`、7 个 `coverage_gap`；生产和观察构建各 16 个 `coverage_gap`，观察字段吻合，起点导入后没有重新同步 |
| 13 组新增 native 回归 | 旧版 9 失败、4 通过；修复后 13 通过。包含队列绕回、另一张同名牌、分支复制、80 能量旋风斩、零能量与化学物 X、死亡清理、空弃牌及格挡对照 |
| CTest | 一次完整运行，334 个入口通过 |
| 累计原版修复验收 | 生产与观察构建各 20 项测试通过，覆盖 70 个原版场景及专项状态核对 |
| 检查器 | 冻结旧构建 41 项通过；第九轮旧构建负向检测 2 项通过，历史期望没有修改 |
| 搜索模块 | 8 次战斗的单次调用与批量调用在 1、4 线程下吻合；输入状态、RNG 和分支隔离核对通过 |
| 可移植补丁 | 性能版与 E121 两份源码应用通过；各检查 3 个改动编译单元；性能版改动文件与本轮编译输入哈希吻合 |

弃牌计数在观察构建中逐观察点比较；生产 Python 绑定没有导出该字段，生产核心通过 C++ 计数回归核对。不能把生产 Python 重放结果表述为完整字段覆盖。

- [旧版重放](../../runs/parity-repair-20260928-limit-backlog/replay-before/report.json)、[生产重放](../../runs/parity-repair-20260928-limit-backlog/replay-production/report.json)、[观察重放](../../runs/parity-repair-20260928-limit-backlog/replay-audit/report.json)
- [新增 C++ 回归](../alignment/tests/limit_backlog_rules.cpp)、[原版合同](../alignment/tests/test_limit_backlog_original.py)、[修复前后结果](../../runs/parity-repair-20260928-limit-backlog/focused-before-after.json)、[完整回归日志](../../runs/parity-repair-20260928-limit-backlog/ctest.log)
- [运行时身份](../../runs/parity-repair-20260928-limit-backlog/runtime.json)、[交付核对](../../runs/parity-repair-20260928-limit-backlog/verification.json)、[持续排查清单](CONTINUOUS-AUDIT.md)

本轮复用保存的原版捕获，没有把重复重放计为新原版场景。参考环境为原版 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod。结论不覆盖无 Mod 原版、其他种子、完整动态分支和私有状态，也不代表胜率改善。
