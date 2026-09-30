# 2026-09-28 抽牌能力顺序与红头骨历史状态修复

本轮处理[第七轮检查](RESULTS-20260928-ROUND7.md)的两类差异：抽牌能力按获得顺序触发；红头骨保留是否生效的历史，避免增加生命上限后误扣力量或漏掉下次加力量。14 个原版场景的被比较字段在生产与观察构建中吻合。完整一致性状态为 `INCOMPLETE`，后续[第八轮检查](RESULTS-20260928-ROUND8.md)确认两类待修差异。

工作位于隔离 worktree `sts-rl-agent-parity`，分支 `codex/original-simulator-parity-20260927`。本轮没有提交、推送或更新玩家安装的 Mod。新运行时位于 [parity-repair-20260928-draw-skull](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/runtime.json)，此前源码、二进制、样本及来源记录保留。

## 修复行为

抽牌复用玩家现有的能力顺序记录，不增加另一份顺序状态。`CardManager::draw` 先把虚空自身的扣能量动作放入队尾，再按 `powerOrder` 遍历进化与火焰吐息；禁止抽牌时不添加进化抽牌动作。动作使用执行分支的 `BattleContext`，分支复制不引用另一场战斗。顺序依据原版 [`AbstractPlayer.draw`](</Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/native-complete-source/source/com/megacrit/cardcrawl/characters/AbstractPlayer.java:1614>)，实现见 [CardManager.cpp](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/source/src/combat/CardManager.cpp:401)。

红头骨不能依靠“当前生命是否低于当前上限的一半”还原历史。新增 `Player.isBloodied` 与 `Player.redSkullActive`，在跨越半血线时更新，在复制战斗时按值复制；加减力量保留前轮修复的排队行为。初始化、失血、回血、增加生命上限和快照导入共享这份状态。实现见 [Player.cpp](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/source/src/combat/Player.cpp:212) 与 [BattleContext.cpp](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/source/src/combat/BattleContext.cpp:54)。

新增的受控反例说明保存历史的必要性：41／80 生命、红头骨未生效，持有绽放印记时喝果汁，最大生命变为 85，但回血被阻止，原版两个标记保持 `false`。接着打放血，生命变为 38，原版此时获得 3 力量。旧模拟器把 41／85 当作此前处于半血，漏掉这次触发；修复后力量为 3。

生产导出器新增 `is_bloodied` 与红头骨私有 `isActive` 的只读导出，[快照桥接](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/steam/steam_mcts.py:580)负责传递。检查器在起点导入这些标记，后续动作不回填原版状态。旧快照缺少字段时保留按生命推导的兼容行为，不能据此恢复丢失的历史。旧引擎没有对应字段时，检查器记录 `unmapped_simulator_field`，不把未知计数送入旧比较器造成异常。

## 原版对照

| 场景组 | 数量 | 结果 |
|---|---:|---|
| 第七轮能力顺序、小地精之角和能量对照 | 4 | 被比较字段吻合 |
| 第七轮进食、果汁和半血阈值对照 | 4 | 被比较字段吻合 |
| 绽放印记、再次失血、神圣树皮、虚空与小地精之角 | 4 | 被比较字段吻合 |
| 虚空与火焰吐息的致命／非致命对照 | 2 | 被比较字段吻合，额外核对最终能量为 3、生命为 47 |

前 8 例复用不可变的旧原版样本；新增样本为 [draw-skull-repair-original.json.gz](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/draw-skull-repair-original.json.gz) 与 [void-terminal-original.json.gz](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/void-terminal-original.json.gz)，均为完整捕获文件的字节复制。[来源清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/parity/tests/fixtures/provenance.json)保留逐行、场景、游戏及 Mod 身份。

14 例的[旧引擎重放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/replay-before/report.json)记录 5 个 `mismatch` 和 9 个 `coverage_gap`；[生产重放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/replay-production/report.json)、[观察重放](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/replay-audit/report.json)各记录 14 个 `coverage_gap`，且 `observed_match=true`。终局通用比较存在选择界面缺口，最终能量由验收测试读取原版审计字段 `player_energy` 单独核对；不能把通用报告解释为完整终局字段一致。

首次扩展捕获的四例中，一例用了错误的遗物 ID `Sacred Bark`，属于夹具错误；修正为 `SacredBark` 后重捕获四例。第二次原版轨迹完整，但三个案例的旧引擎比较遇到新增计数字段，属于适配器错误。修正字段映射后重放同一批捕获；错误报告保留，未计为通过。[尝试记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/original-extended-v2/report.json)与来源清单记录这一区别。

## 验证和构建

| 检查 | 结果与证据 |
|---|---|
| 新增 8 组 native 行为回归 | 修复前 6 失败、2 通过；修复后 8 通过，见[前后对照](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/focused-before-after.json) |
| CTest 311 个入口 | 首次 310 通过、1 失败；纠正旧虚空终局预期后，失败入口与更新的原版合同入口重跑通过。不是一次全绿的全量运行，见[首次日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/ctest.log)、[重跑日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/ctest-rerun.log) |
| 原版修复验收 | 生产与观察各 13 项通过，覆盖此前 32 例与本轮 14 例，另含历史标记导入检查，见[生产日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/production-original-tests.log)、[观察日志](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/audit-original-tests-final.log) |
| 检查器与旧发现检测 | 冻结旧构建的 41 项检查器测试、第七轮 2 项检测通过，旧负向预期保留 |
| 搜索运行时 | `slaythespire`、`fightsim`、观察模块重建；8 次单次／批量战斗在 1、4 线程下结果吻合，输入状态及 RNG 不变，见[记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/runtime-smoke.json) |
| 补丁可移植性 | 性能版与 E121 源码各应用通过，各 4 个修改翻译单元语法检查通过，见[记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/portable-verification.json) |

旧 native 用例曾预期火焰吐息结束战斗时虚空不扣能量，修复顺序后该用例失败。两条新增原版捕获证实扣能量排在伤害之前，因此将致命场景预期从 4 改为 3；没有修改原版样本。另两处旧红头骨测试通过手工修改生命构造半血，改为实际失血并结算，使历史标记与状态一致，原行为预期保持。

[draw_skull_state.patch](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/draw_skull_state.patch) 接在 `exhaust_skull_order.patch` 后应用。它改变 `Player` 布局，核心、搜索和 Python 绑定需一起重编。分发文件身份见[源码清单](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/sim_patch/alignment/draw-skull-state-manifest.json)。首次 E121 应用因无关的文件尾空行差异失败；删除该差异后两种源码应用通过，增量重编的三个模块哈希不变，见[重编记录](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/whitespace-rebuild.json)。

验收范围是带 BaseMod、CommunicationMod、SpireLabLogic 等 Mod 的原版隔离运行时，以及记录中的状态和动作。命令边界状态来自捕获，动作内部先后次序来自源码核对；没有逐动作 Java 事件流。本轮修复捕获使用的 10 个实例退出，后续排查使用的 8 个实例退出。完整动态分支、私有状态、合法动作和高阶组合覆盖待完成。[源码证据](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/source-audit.json)、[交付核对](/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-parity/runs/parity-repair-20260928-draw-skull/verification.json)记录范围及文件身份。
