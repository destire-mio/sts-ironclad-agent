# 2026-09-28 斗技场激怒修复与第十轮排查

斗技场第二场战斗中，奴隶头子位于第一个位置，地精大块头位于第二个位置。旧模拟器在打出技能时检查 `monsters.arr[0]`，漏掉第二个位置的激怒。原版的 `UseCardAction` 遍历所有怪物，`AngerPower` 把所属怪物的加力量动作放入队首。

修复遍历怪物队列，每个激怒动作保存目标位置和触发层数，执行时访问所属分支的怪物。死亡目标跳过加力量。改动范围为 `BattleContext.cpp` 的技能回调，没有修改怪物排列、原版输入或观察期望。[补丁](../colosseum_enrage.patch)接在 `limit_backlog_rules.patch` 后应用，核心、搜索和绑定需要重编。[分发清单](../alignment/colosseum-enrage-manifest.json)记录文件哈希。

| 原版场景 | 原版大块头力量 | 修复前 | 修复后 |
|---|---:|---:|---:|
| 斗技场，大块头激怒生效后打出防御 | 3 | 0 | 3 |
| 上述状态打出普通缴械 | 1 | -2 | 1 |
| 上述状态打出升级缴械 | 0 | -3 | 0 |
| 打出打击对照 | 0 | 0 | 0 |

四个单只大块头对照覆盖普通／升级缴械与 998 力量、低力量、上限下的防御。结果吻合，排除了本轮最初的“加力量排队导致缴械上限不同”假设：原版使用队首，先加力量再执行缴械。首个怪物位置的行为因此作为回归对照保留。

八个场景来自八个独立原版 JVM。旧生产与观察构建重放各有 3 个差异、5 个吻合场景；新构建各有 8 个 `coverage_gap`，被比较字段吻合，每条序列从起点导入后没有重新同步。[原版来源](tests/fixtures/provenance.json)记录样本、场景、实例和 Mod 身份，捕获文件没有修改。

| 检查 | 结果 |
|---|---|
| 8 组 C++ 回归 | 修复前 5 失败、3 通过；修复后 8 通过，覆盖位置、层数、力量上限、队列复制、死亡目标与非技能对照 |
| CTest | 一次完整运行，343 个入口通过 |
| 原版修复验收 | 生产与观察构建各 22 项通过，累计覆盖 78 个原版场景和专项状态核对 |
| 搜索模块 | 8 次战斗在单次／批量 1、4 线程调用下吻合，输入状态、RNG 与分支隔离核对通过 |
| 可移植补丁 | 性能版、E121 应用通过，各检查改动的编译单元 |
| 实例清理 | 本轮 8 个原版 JVM 退出，清理记录的剩余进程为空 |

- [生产与观察运行时](../../runs/parity-repair-20260928-colosseum-enrage/runtime.json)、[生产重放](../../runs/parity-repair-20260928-colosseum-enrage/replay-production/report.json)、[观察重放](../../runs/parity-repair-20260928-colosseum-enrage/replay-audit/report.json)
- [新增回归](../alignment/tests/colosseum_enrage.cpp)、[原版合同](../alignment/tests/test_colosseum_enrage_original.py)、[修复前后结果](../../runs/parity-repair-20260928-colosseum-enrage/focused-before-after.json)、[CTest 日志](../../runs/parity-repair-20260928-colosseum-enrage/ctest.log)
- [源码核对](../../runs/parity-repair-20260928-colosseum-enrage/source-audit.json)、[交付核对](../../runs/parity-repair-20260928-colosseum-enrage/verification.json)、[实例清理](../../runs/parity-20260928/round10-cleanup.json)

第十轮还用上一批修复后的构建重放了种子 129 的历史自然整局：1002 条命令、909 个观察点，到第 51 层失败终局，被比较字段吻合；旧版的 83 个弃牌计数差异消失。914 个战斗外历史样本刷新后保持 317 个原始表示差异，其中 270 个场景涉及遗物计数、47 个涉及洗牌 RNG、1 个涉及瓶装候选顺序，类别有重叠。这些观察差异需要对应状态与时点归因，不能计为规则缺陷。[排查汇总](../../runs/parity-20260928/round10-search-summary.json)保存报告身份。

改动位于隔离 worktree `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`；没有提交或推送。参考环境为原版 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod。当前结论不覆盖无 Mod 原版、全部可达状态或胜率。持续 goal 保持 active，剩余队列见[排查清单](CONTINUOUS-AUDIT.md)。
