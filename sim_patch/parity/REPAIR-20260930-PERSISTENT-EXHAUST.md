# 2026-09-30 医疗箱／蓝蜡烛的消耗标记与后续移牌修复

医疗箱和蓝蜡烛把打出的那张牌的 `exhaust` 设为 true。奇怪的勺子把牌送回弃牌堆后，这个标记保留；模拟器曾把消耗记在一次出牌队列项上，下一次结束回合时把灼伤、悔恨、疑虑送入弃牌堆，漏掉勺子的随机判定和消耗回调。

R54／R55 的 12 个原版场景包含 7 个反例和 5 个对照。修复后，86 条动作、98 个检查点的比较字段吻合。R56／R57 的九个后续场景完成检查；这次候选范围没有证实的待修差异。参考运行时是安装的原版 JAR 加 Mod，完整一致性状态为 `INCOMPLETE`。

## 改动与可观察结果

- 卡牌实例保存遗物增加的消耗属性；同名但没打出的牌保留各自的属性。
- 移牌、洗牌、分支复制保留属性；原版的 `makeStatEquivalentCopy` 从 `makeCopy` 创建新对象，不复制这种运行时改动，相关生成与复制入口遵循此规则。
- 结束回合触发状态／诅咒效果后，复用 `OnAfterCardUsed` 清理，读取消耗属性、判定奇怪的勺子并调用消耗效果。删除只负责弃牌的旧辅助函数。
- 原版 CommunicationMod 提供 `exhausts` 字段。快照桥接、native 导入和只读卡牌属性保留该字段，包含从真实中途观察点恢复后执行原版后续动作的检查。

一组医疗箱、奇怪的勺子、无惧疼痛和灼伤的场景中，两张牌在第三次结束回合时消耗并产生 6 格挡。第四回合观察点，原版剩 61 血，旧模拟器剩 55 血，修复版剩 61 血。下一回合原版为 45 血，旧模拟器为 35 血。旧运行时在首处随机数分歧后执行固定结束回合输入的[诊断](../../runs/parity-repair-20260930-persistent-exhaust/continued-before.json)保留全部差异，没有重新导入后态；这份诊断不计为验收。

## 验证

| 检查 | 结果 |
|---|---|
| 同一批 12 个原版场景 | 修复前 7 个 mismatch、5 个 coverage_gap；生产和观察构建各 12 个 coverage_gap，所比较字段吻合 |
| 真实中途快照 | 八个恢复位置、18 条后续动作吻合，包含有标记和没标记的同名牌 |
| 消耗属性与分支隔离 | 21 个场景、160 个检查点读取原版逐牌 `exhausts`，139 条动作检查兄弟分支不变、重复执行吻合 |
| 四个负对照 | 丢失标记、错移牌堆、错误血量、错误 RNG 被拒绝 |
| 完整回归 | 473 个 CTest 入口通过；本次源代码完成后的第一次完整运行耗时 94.60 秒 |
| 历史自然轨迹 | 1002 条原版命令、837 个战斗比较点吻合；第 51 层失败，分数 1786，不代表胜率提升 |
| 搜索与批量运行 | 八场单次调用与 1／4 线程批量调用吻合，输入状态、RNG 和副本隔离通过 |
| 补丁可移植检查 | 性能版与 E121 两份来源应用时 fuzz 为 0；十个编译单元的语法检查通过 |

标准比较器和原版观察器没有修改。逐牌消耗属性在[附加核对](../../runs/parity-repair-20260930-persistent-exhaust/flag-comparison-production.json.gz)中检查，标准比较器的未投影字段记录保留。历史快照中的百年积木缺失状态保留一项 coverage_gap。

## 后续寻找

R56 四个新场景覆盖受颈圈限制的重复自动出牌、复制药水、死灵诅咒生成新实例，以及结束回合消耗触发抽牌。R57 五个新场景覆盖 Havoc 强制消耗不能出的灼伤、不能出的状态／诅咒、Secret Weapon／Secret Technique 缺少剩余候选，以及前一张牌杀死目标后的双发／死灵之书复制。这九个场景的比较字段和逐牌消耗属性吻合。[R56](../../runs/parity-20260930/round56-persistent-exhaust-neighbors-pilot-v1/report.json)、[R57](../../runs/parity-20260930/round57-autoplay-can-use-pilot-v1/report.json)。

一段遗留的 `CardInstance::triggerOnExhaust` 定义包含铃铛诅咒逻辑，但源代码中没有调用者。战斗使用 `BattleContext::triggerAndMoveToExhaustPile` 处理死灵诅咒，R56 原版后续验证新实例行为。不能用遗留函数中的文本代替实际调用链来判定缺陷。

## 交付入口与边界

- [规则补丁](../persistent_exhaust.patch)、[分发清单](../alignment/persistent-exhaust-manifest.json)，接在 `autoplay_exhaust.patch` 后。快照桥接变更位于 `steam/steam_mcts.py`。
- [原版合同](../alignment/tests/test_persistent_exhaust_original.py)、[同输入前后分类](../../runs/parity-repair-20260930-persistent-exhaust/classification.json)、[一手源码绑定](../../runs/parity-repair-20260930-persistent-exhaust/source-audit.json)。
- [运行时身份](../../runs/parity-repair-20260930-persistent-exhaust/runtime.json)、[核验结果](../../runs/parity-repair-20260930-persistent-exhaust/verification.json)、[核验脚本](../../runs/parity-repair-20260930-persistent-exhaust/verify_delivery.py)。

工作位于隔离 worktree `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`；没有提交或推送。生产目录为 `runs/parity-repair-20260930-persistent-exhaust/production-build`，观察目录为同级 `audit/build`。R26 的源码、阶段构建、输入和证据保留原有哈希。

累计验收场景及状态合同为 536；九个后续探索场景不增加这个计数。有限场景无法证明无界动作序列、其他自然种子、无 Mod 原版或未导出私有状态的一致性。当前 goal 接口返回 null；此记录没有创建或关闭 goal。
