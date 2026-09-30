# 2026-09-28 斗技场连续战斗随机状态修复

斗技场第一场战斗结束后，原版在返回事件页面时准备牌组；选择第二场时再次准备牌组。模拟器漏掉返回页面时的洗牌，并在第二场开局重置怪物血量、怪物行动、洗牌、战斗生成牌四组随机状态。结果是第二场的手牌、怪物血量和随机生成牌可能变化。

## 原版证据与根因

本轮使用 6 个独立原版 JVM，经过受控房间入口后，用正常的出牌与事件选择命令推进。两边共用入口观察到的牌组顺序、随机状态和遗物池，之后没有导入原版状态。[场景](specs/colosseum_rng_round15.json)、[不可变捕获](tests/fixtures/colosseum-rng-original.json.gz)、[来源与实例清理](tests/fixtures/provenance.json)记录输入和原版身份。

种子 123 的第一场开局，两边被比较字段相同。原版打出旋风斩获胜后，洗牌计数从 1 变成 2；第二场开局变成 3。旧模拟器返回事件时保持 1，第二场又从 1 开始。原版第二场怪物行动计数为 4、血量随机计数为 5，旧版分别为 2、3。百科全书（Enchiridion）在 `atPreBattle` 选取能力牌，因此返回事件时也消耗一次生成牌随机数；该场景的计数为 1 → 2 → 3。

原版 `AbstractDungeon.nextRoomTransition` 在进入新房间时重设这些随机源；`Colosseum` 的第二场留在当前房间。`Colosseum.reopen` 调用 `AbstractPlayer.preBattlePrep`，其中 `CardGroup.initializeDeck` 洗牌，遗物 `atPreBattle` 回调执行。铁甲战士范围内的这些回调完成源码核对，百科全书的随机选择需要保留。[源码哈希与审查记录](../../runs/parity-repair-20260928-colosseum-rng/source-audit.json)。

试探捕获中的第一版 native 夹具使用请求里的牌组顺序，但 Java 的 `addToBottom` 会插入列表首部。正式回放改用原版入口观察到的主牌组顺序。6 个正式场景的第一场开局在修复前后均吻合；未把夹具顺序错误计入规则缺陷。试探记录保留在 `runs/parity-20260928/round15-colosseum-rng-pilot/`。

## 修改与验证

[补丁](../colosseum_rng.patch)接在 `ethereal_overrides.patch` 后，修改两个规则源文件：返回斗技场事件页面时保留准备牌组及百科全书的随机消耗；第二场从整局对象接收第一场交回的四组随机状态。普通新房间的初始化路径保持原有规则。没有新增随机数补偿表或读取原版后续结果。

| 验证 | 结果 |
|---|---|
| 6 个原版场景 | 修复前 5 个差异、1 个开局对照；修复后生产与观察构建的比较字段吻合 |
| 原版场景范围 | 两个种子、百科全书、扭曲之钳、获胜后离开、第一场开局对照 |
| 比较内容 | 8 组 RNG 的计数和完整状态、牌堆顺序及费用、玩家生命／能量／格挡／力量、怪物生命／格挡／力量、战斗合法动作 |
| 7 个专项 C++ 用例 | 同输入链接旧核心得到 4 失败、3 对照通过；新核心 7 通过，包含分支复制与新楼层对照 |
| 全部 CTest | 374 个入口通过 |
| 累计原版修复合同 | 生产、观察构建各 32 项测试通过，累计覆盖 103 个原版场景及状态合同 |
| 检查器反例测试 | 冻结旧引擎上 41 项通过，保留既有差异检测能力 |
| 可移植补丁 | optimized、E121 两套源码零 fuzz 应用，4 个变更翻译单元语法检查通过 |
| 搜索运行时 | 核心、绑定、fightsim 重编；8 个任务在顺序及 1／4 线程批量执行下相同，输入和兄弟分支未被修改 |

[修复前比较](../../runs/parity-20260928/round15-colosseum-rng-v1/comparison/report.json)、[生产比较](../../runs/parity-repair-20260928-colosseum-rng/replay-production/report.json)、[观察比较](../../runs/parity-repair-20260928-colosseum-rng/replay-audit/report.json)、[专项前后对照](../../runs/parity-repair-20260928-colosseum-rng/focused-before-after.json)、[回归日志](../../runs/parity-repair-20260928-colosseum-rng/ctest.log)。

运行时入口为 `runs/parity-repair-20260928-colosseum-rng/build`，观察构建为同级 `audit/build`。[分发清单](../alignment/colosseum-rng-manifest.json)、[运行时身份](../../runs/parity-repair-20260928-colosseum-rng/runtime.json)、[交付核验](../../runs/parity-repair-20260928-colosseum-rng/verification.json)绑定源码、二进制和捕获。

```bash
python -m sim_patch.parity.colosseum \
  --source sim_patch/parity/tests/fixtures/colosseum-rng-original.json.gz \
  --executable runs/parity-repair-20260928-colosseum-rng/build/colosseum_rng_probe \
  --out runs/colosseum-rng-replay-new-directory
```

这些结果限于安装的 Mod 原版参考配置和给定动作前缀。未比较的遗物计数、全部能力／私有字段、第二场结束奖励、无 Mod 原版与完整动态分支保留覆盖缺口。结果标记为 `coverage_gap`，完整一致性为 `INCOMPLETE`。

原版事件入口及 `atPreBattle` 回调完成与本缺陷相关的源码查找；本批没有待修证实差异。战斗外观测阶段、选择映射及其他交互范围保留在[持续排查清单](CONTINUOUS-AUDIT.md)，goal 为 active。7 个本轮实例（含试探实例）退出。没有提交、推送或修改主工作树。
