# 2026-09-28 消耗牌能力顺序与红头骨修复

本轮修复[第六轮检查](RESULTS-20260928-ROUND6.md)中的两类差异。12 个原版场景在生产构建与观察构建中吻合，分类为 `coverage_gap`；此前疼痛、虚空、群攻、鸟面瓮的 20 个场景通过验收。全量一致性状态为 `INCOMPLETE`。改动位于隔离 worktree `sts-rl-agent-parity`，没有提交或推送。

## 实现

消耗牌回调沿用玩家现有的 `powerOrder`，按能力获得顺序处理黑暗之拥、无惧疼痛。遗物回调位于能力回调前，卡牌自身的消耗回调位于其后。没有增加第二份能力顺序状态，也没有修改获得、叠加、移除能力的规则。

红头骨跨过半血时，把加 3／减 3 力量动作加入队首。致命伤先排入加力量，复活回血再把减力量插到它前面，保留原版的先减后加及力量上下限行为。减力量复用现有负面效果动作，因此人工制品在动作执行时判断和消耗。

`Player::heal` 与 `increaseMaxHp` 增加所属 `BattleContext` 参数，回血动作、复活、鲜血神像、进食、果汁和相关怪物事件入口传入对应战斗。动作执行时读取所属分支，队列没有捕获另一个分支的玩家引用。开战回血保留禁止触发红头骨减力量的参数，原有魔法花与绽放印记处理保留。

[分发补丁](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/exhaust_skull_order.patch)接在 `aoe_urn_order.patch` 后，修改 5 个模拟器文件。两处测试／探针调用改为使用已有 `HealPlayer` 动作；战斗外探针在回血后结算动作，与原版探针的 `flush` 边界对应。接口变化要求重编核心、搜索和绑定。

## 原版验收

复用第六轮 8 个场景，补充 4 个独立原版场景：负力量下限、蜥蜴尾巴＋魔法花、回血时有／无人工制品。样本为原始捕获文件的字节复制，来源见[来源清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)。

| 场景 | 原版 | 修复前 | 修复后 |
|---|---:|---:|---:|
| 无惧疼痛先于黑暗之拥，势不可挡 5 伤害：存活敌人生命 | 20 | 15 | 20 |
| 同上，势不可挡升级为 7 伤害：存活敌人生命 | 20 | 13 | 20 |
| 红头骨＋树皮＋精灵，从 999 力量致命伤复活 | 999 | 996 | 999 |
| 同上，从 -999 力量开始 | -996 | -999 | -996 |
| 红头骨＋蜥蜴尾巴＋魔法花，从 999 力量复活 | 999 | 996 | 999 |

其余 7 个对照的被比较字段保持吻合。12 个场景修复前有 5 个反例，修复后被比较字段吻合。对照包括交换能力获得顺序、改抽普通牌、低力量、去掉树皮或红头骨，以及人工制品是否抵消减力量。三个复活反例使用设定的致命伤与力量边界，不提供自然对局出现频率。

- [补充场景](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/specs/exhaust_skull_repair_controls.json)、[补充原版样本](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/exhaust-skull-repair-original.json.gz)、[补充原版捕获](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/original-extended/report.json)
- [生产构建回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/replay-production/report.json)、[观察构建回放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/replay-audit/report.json)

## 回归、分发与限制

| 检查 | 结果 |
|---|---|
| 新增原生检查 | 8 组通过；旧引擎 6 组失败、2 组对照通过 |
| CTest | 302 个入口完成验证：首轮 301 个通过，修正一项测试期望后，该入口通过 |
| 原版样本测试 | 两种构建各 8 项通过，包含本轮 12 个和此前 20 个场景 |
| 冻结检查器回归 | 41 项通过，旧差异预期保留 |
| 训练模块 | 重建 `slaythespire`、`fightsim`；8 次战斗的单次／批量结果吻合，输入状态、RNG 和分支复制检查通过 |
| 分发补丁 | 性能优化源码与归档 E121 加先前补丁后可应用，4 个修改的编译单元通过语法检查 |

新增原生检查覆盖能力叠加与移除后重新获得、禁抽、恐慌按钮、等待结算时复制分支、力量上下限、人工制品、绽放印记及死亡终局。初次测试把“恐慌按钮会阻止无惧疼痛给予格挡”作为期望，导致旧版与修复版在该子案例失败。核对原版 `NoBlockPower.modifyBlockLast` 与 `GainBlockAction` 后，期望改为能力给予 3 格挡；没有为这次测试修正改写模拟器规则。初次结果与修正后的结果分开保留。

- [原生检查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/tests/exhaust_skull_order.cpp)、[原版验收入口](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/tests/test_exhaust_skull_original.py)
- [初次原生结果](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/focused-before-after.json)、[修正后的前后对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/focused-before-after-corrected.json)
- [CTest 首轮日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/ctest.log)、[失败入口复验](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/ctest-rerun.log)、[旧引擎原版验收失败](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/baseline-original-tests.log)
- [生产构建测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/production-original-tests.log)、[观察构建测试日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/audit-original-tests.log)、[冻结检查器日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/checker-frozen-tests.log)
- [训练模块检查](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/runtime-smoke.json)、[补丁分发核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/portable-verification.json)、[分发清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/exhaust-skull-order-manifest.json)

新运行时位于 [build](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/build)，观察构建位于同级 `audit/build`。[运行时清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/runtime.json)与[交付核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-exhaust-skull/verification.json)记录文件身份和验证结果。旧构建、旧检测入口、历史原版样本保持原身份。

原版对照为游戏 JAR 加 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的隔离逻辑运行时。有限受控场景与本地回归不构成无 Mod 原版、自然整局、归档 E121 运行时或全量可达状态的一致性证明。修复后继续检查的新发现见[第七轮记录](RESULTS-20260928-ROUND7.md)。
