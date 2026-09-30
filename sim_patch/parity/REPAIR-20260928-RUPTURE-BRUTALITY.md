# 2026-09-28 撕裂与残暴结算顺序修复

本轮处理[第八轮检查](RESULTS-20260928-ROUND8.md)的两类差异：撕裂加力量进入队首，残暴先排抽牌再排失血。同一批 8 个原版场景的被比较字段在生产与观察构建中吻合，累计修复验收覆盖 54 个原版场景。后续[第九轮检查](RESULTS-20260928-ROUND9.md)发现突破极限绕过人工制品的一类待修差异；完整一致性状态为 `INCOMPLETE`。

改动位于隔离 worktree `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`，没有提交或推送。新[运行时](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/runtime.json)与此前构建使用不同目录，旧源码、模块和捕获样本保留。

## 两处修复

原版 [`RupturePower.wasHPLost`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/RupturePower.java:32>)把加力量动作放入队首，等当前伤害与复活动作结束后结算。模拟器的 `Player::hpWasLost` 改为 `addToTop(Actions::BuffPlayer<PS::STRENGTH>(amount))`，触发时保存层数，执行时使用所属战斗的玩家。复活导致红头骨失效时，其减力量动作后入队首、先执行，力量上限不再吞掉撕裂的增量。

原版 [`BrutalityPower.atStartOfTurnPostDraw`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/powers/BrutalityPower.java:35>)先排抽牌，再排失血。模拟器调换这两条入队语句：以血还血被抽到后，由混乱随机定费，再因残暴失血降费。改动复用现有动作和能力顺序记录，没有增加状态或回填原版结果。两处实现见 [Player.cpp](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/source/src/combat/Player.cpp:340)。

| 原版场景 | 修复前 | 修复后与原版 |
|---|---|---|
| 999 力量，撕裂 +1／+2，红头骨与瓶中精灵复活 | 996／996 力量 | 997／998 力量 |
| 上述组合的低力量、移除红头骨对照 | 吻合 | 吻合 |
| 残暴、混乱、普通／升级以血还血 | 1 费，打出后剩 2 能量 | 0 费，打出后剩 3 能量 |
| 移除混乱、钨合金棍阻止失血对照 | 吻合 | 吻合 |

每条轨迹在起点导入一次，后续独立执行对应动作，检查状态、合法动作、RNG 和分支复制。原版样本沿用[撕裂复活样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/rupture-revive-original.json.gz)、[残暴混乱样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/brutality-confusion-original.json.gz)，未修改预期数据。[修复前重放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/replay-before/report.json)有 4 个 `mismatch`、4 个 `coverage_gap`；[生产重放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/replay-production/report.json)与[观察重放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/replay-audit/report.json)各有 8 个 `coverage_gap`，被比较字段吻合。缺口没有改为通过。

## 验证

| 检查 | 结果 |
|---|---|
| 新增 8 组 native 回归 | 修复前 5 失败、3 通过；修复后 8 通过。覆盖复活上限、队列复制、触发层数、非自身伤害、伤害阻止、混乱费用、禁止抽牌与叠层残暴 |
| CTest | 320 个入口通过，一次完整运行，无失败 |
| 原版修复验收 | 生产与观察构建各 15 项通过：此前 46 例与本轮 8 例，包含历史状态导入及原有终局能量专项核对 |
| 检查器检测能力 | 冻结旧构建的 41 项检查器测试通过，第八轮旧构建的 2 项负向检测通过，旧期望保持 |
| 搜索模块 | 核心、生产绑定、观察绑定、`fightsim` 重建；8 次单次／批量战斗在 1、4 线程下结果一致，输入状态和 RNG 不变，分支复制隔离 |
| 可移植补丁 | 性能版与 E121 源码应用通过，各对修改的 `Player.cpp` 完成语法检查 |

- [native 测试](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/tests/rupture_brutality_order.cpp)、[修复前后结果](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/focused-before-after.json)、[CTest 日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/ctest.log)
- [原版验收测试](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/tests/test_rupture_brutality_original.py)、[生产日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/production-original-tests.log)、[观察日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/audit-original-tests.log)
- [检查器日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/checker-frozen-tests.log)、[旧检测日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/round8-frozen-tests.log)、[运行时检查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/runtime-smoke.json)、[补丁应用记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/portable-verification.json)

[rupture_brutality_order.patch](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/rupture_brutality_order.patch)接在 `draw_skull_state.patch` 后应用，重编核心、搜索与绑定，不混用旧核心对象。[分发清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/rupture-brutality-order-manifest.json)、[源码核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/source-audit.json)、[交付核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-rupture-brutality/verification.json)记录哈希与检查范围。

范围为原版 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的受控隔离环境，不构成无 Mod 原版、自然整局或胜率结论。现场证据是命令边界状态，动作内部顺序依据源码；完整动态分支、私有字段、合法动作和高阶交互覆盖待完成。本轮修复复用原版样本；后续排查启动的 8 个原版实例退出，清理记录随第九轮报告保存。
