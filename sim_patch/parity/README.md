# 原版与模拟器一致性检查

这个工具让原版和模拟器接受对应的输入，在决定下一步操作的位置比较状态。发现分歧后保存输入、原版响应、模拟器结果和首个分歧前缀。每个未比较字段、未支持操作、未执行分支都保留为缺口。

**验收状态为 INCOMPLETE。工具没有证明所有可达状态一致，也不能承诺找完所有缺陷。** 当前范围沿用项目的 Ironclad A20 Heart，排除 Prismatic Shard；这不是其他角色、其他进阶等级、所有模组或所有帧时序的验收。

## 工作方式

| 检查 | 作用 | 边界 |
|---|---|---|
| `inventory` | 从原版源码与内容清单列出卡牌、遗物、药水、事件、怪物、流程、条件分支、共享触发时机 | 分支是静态扫描候选，没有插桩执行覆盖；共享触发时机的二元组合不包含所有交互 |
| `replay` | 重放原版历史操作序列，比较生命、格挡、能量、牌堆顺序、随机数、计数、状态等 | 在案例起点导入一次；未知字段和选牌过程的缺失保留为缺口 |
| `live` | 为每个受控案例启动独立原版 JVM 和存档副本，生成新证据后交给独立模拟器进程 | 原版 JAR 与项目运行时 Mod 共同决定行为；不能将此环境称为无 Mod 原版 |
| `natural` | 从种子开局，经过战斗、奖励、地图等环节；中途不导入状态 | 默认遇到首个分歧停止；`--continue-after-mismatch` 记录后续差异，后续结果可能受首个分歧影响 |
| `explore` | 从原版提供的合法动作出发遍历操作树 | 用户指定深度和节点数；未支持的选牌、战斗外继续路径留在待检查列表；不合并看似相同的状态 |
| `outside` / `outside-live` | 检查战斗外记录，保留牌堆、候选牌、奖励顺序及原始计数差异 | 初始状态全部字段的等价尚未证明；原始表示差异不等于规则缺陷 |
| `summary` | 汇总多份报告及源码覆盖缺口 | 同字段分组不表示同根因；重复复现记录计入案例数 |

原版的合法动作枚举使用原版 `canUse`，模拟器枚举使用动作校验器，不使用 MCTS 搜索的剪枝动作集合。原版观察器会比较枚举前后的可见标量和 RNG，观察到变化时不声明动作域完整。这项检查不涵盖观察器没有导出的引用、字符串、静态私有状态。

本机 BaseMod 的 `ConsistentEtherealPatch` 会把回合结束的虚无牌洗牌改成基于游戏种子、楼层、回合数的固定种子洗牌；无此补丁的 Java 规则使用 `Collections` 的共享随机源。新现场证据记录所有运行时 Mod 的哈希、启用列表、`BaseMod.fixesEnabled` 和共享随机源的状态。原版种子相同不能消除这项运行环境差异。

诊断场景可添加 `"original_profile":"without-consistent-ethereal"`，从本次案例的 BaseMod 副本中移除这一补丁的两个类。此选项用于核对补丁影响，其余 Mod 保留，因此不构成无 Mod 原版的验收。默认值 `installed` 使用现有运行时。未知场景参数和卡牌参数会报错，例如升级卡牌应使用 `{"card":"Rampage","upgrades":1}`。

受控场景的 `current_hp` 设置当前生命，保留最大生命；默认最大生命为 80，已有的 `hp` 参数会把当前和最大生命设为同一个值。`current_hp` 必须是 1 到最大生命之间的整数。这个参数修改案例起点，不修改原版伤害或回复规则。

遗物夹具默认添加构造后的实例，不执行回合开始初始化。验证精致折扇一类回合计数遗物时，应设置与待测时点对应的 `relic_counter`，或使用 `initialize_relics:true` 执行战斗与回合开始逻辑；后者可能引入其他开战效果。起点导入检查不能替代这项核对，因为部分原版私有计数没有对应映射。

对受控战斗序列，检查器为每步创建两个模拟器副本：一个用于核对父分支执行是否污染兄弟分支，一个执行同样的动作核对可重复性。指纹覆盖导出的状态，不是全部进程内存的证明。每个模拟器案例使用独立子进程，超时或崩溃会成为该案例的结果，后续案例继续执行。

## 运行环境

在此 worktree 根目录运行命令。回放使用 Python 3.12 和同版本 ABI 的本机扩展；现场运行需要安装了 `spire_lab` 的项目虚拟环境、本机授权的原版游戏和现有 `ironclad-alignment/oracle`。工具为案例克隆实例，不连接玩家的游戏进程。结束时检查所拥有的实例进程是否退出，并写入 `cleanup.json`。

本次测试的隔离扩展位于 `runs/parity-20260927/audit-engine/build`。该扩展从性能优化版的哈希清单复制规则源码，仅在绑定层增加只读状态导出。`audit-engine-frozen-inputs` 是冻结 CMake、探针源码和构建输入后的构建验证版本。

```sh
PARITY_PY=/Users/destire/Documents/Codex/2026-09-10/new-chat-2/outputs/spire-lab/.venv/bin/python
PARITY_ENGINE="$PWD/runs/parity-20260927/audit-engine/build"
PARITY_ORACLE="$PWD/../ironclad-alignment/oracle"

# 一条历史序列；--source 可以重复提供
"$PARITY_PY" -m sim_patch.parity replay \
  --engine "$PARITY_ENGINE" \
  --source sim_patch/alignment/tests/fixtures/original-repair-cards.json.gz \
  --case 0 --out runs/my-parity-recorded

# 独立原版进程生成场景
"$PARITY_PY" -m sim_patch.parity live \
  --engine "$PARITY_ENGINE" --oracle "$PARITY_ORACLE" \
  --specs sim_patch/parity/specs/combat_controls.json --out runs/my-parity-live

# 有限范围内枚举原版操作；剩余路径写入 tree.json
"$PARITY_PY" -m sim_patch.parity explore \
  --engine "$PARITY_ENGINE" --oracle "$PARITY_ORACLE" \
  --spec sim_patch/parity/specs/tiny_tree.json \
  --depth 1 --max-nodes 3 --out runs/my-parity-tree

# 原版历史自然整局；若去掉 --oracle，则使用历史 RPC 记录
"$PARITY_PY" -m sim_patch.parity natural \
  --engine "$PARITY_ENGINE" --oracle "$PARITY_ORACLE" \
  --source sim_patch/alignment/tests/fixtures/original-natural-trace.json.gz \
  --prefix-steps 7 --out runs/my-parity-natural

# 历史整局遇到分歧后继续；不恢复状态，记录后续差异与前序分歧标记
"$PARITY_PY" -m sim_patch.parity natural \
  --engine "$PARITY_ENGINE" \
  --source sim_patch/alignment/tests/fixtures/original-natural-trace.json.gz \
  --continue-after-mismatch --out runs/my-parity-natural-continued

# 检查战斗外候选顺序；现场捕获的报告位于 comparison/ 子目录
"$PARITY_PY" -m sim_patch.parity outside-live \
  --engine "$PARITY_ENGINE" --oracle "$PARITY_ORACLE" \
  --executable "$PARITY_ENGINE/outside_probe" \
  --specs sim_patch/parity/specs/bottle_order.json --out runs/my-parity-bottle
```

所有运行目录必须是新目录，防止覆盖旧证据。`--case-timeout` 约束单个 native 案例；原版启动握手等待上限为 180 秒，写入案例身份记录，启动后的 RPC 有独立超时。启动超时记录为 `original_error`，不计作规则差异或通过。自然整局未采用逐案例子进程，进程级挂起/崩溃隔离是它的剩余缺口。

战斗外案例通过 `ops: [{"battle":true}]` 进入战斗且观察点仍在战斗时，检查器读取 `BattleContext` 的生命、金币、随机数；战斗结束后读取 `GameContext`。这项调整改变探针输出，不改变模拟器规则。额外导出的字段没有原版配对时保留为缺口；事件和存档进入战斗的时点对齐不在这项调整范围内。

重建观察扩展：

```sh
"$PARITY_PY" -m sim_patch.parity.build_engine \
  --source ../sts-rl-agent-sim-perf/runs/simulator-perf-20260926/variants/optimized-queue \
  --source-manifest ../sts-rl-agent-sim-perf/runs/simulator-perf-20260926/build/optimized-queue/build-report.json \
  --json-include ../sts-rl-agent-sim-perf/runs/simulator-perf-20260926/json \
  --out runs/my-parity-engine
```

执行检查器测试：

```sh
PARITY_TEST_ENGINE="$PARITY_ENGINE" "$PARITY_PY" -m unittest \
  sim_patch.parity.tests.test_core sim_patch.parity.tests.test_native -v
```

测试包括伤害、随机数、顺序、可用动作、新增未知字段、空轨迹、未知命令、进程退出与超时，以及本次原版捕获的赌徒药水计数差异。最后一类测试针对冻结版本的已知发现；修复模拟器后，应复核该发现的预期分类，不能修改原版证据让错误版本通过。

第二轮补充暴走与两种复制效果叠加的伤害反例、单种复制效果对照、遇到前序分歧后发现新的伤害差异、战斗与战后状态归属，以及对照端补丁移除的隔离测试。结果见 [第二轮记录](RESULTS-20260927-ROUND2.md)。

第三轮检查带壳寄生怪的致命吸血与复活、旋风斩与精致折扇的荆棘结算顺序。结果及对照见 [第三轮记录](RESULTS-20260927-ROUND3.md)。

第四轮检查疼痛与撕裂的失血来源、虚空与符文立方体触发抽牌时的能量结算顺序。结果及对照见 [第四轮记录](RESULTS-20260927-ROUND4.md)。

这两处规则的补丁、修复版运行时和同一批原版样本验收见[修复记录](REPAIR-20260927-PAIN-VOID.md)。`tests/test_native.py` 保留冻结旧引擎的差异检测预期；修复版验收入口为 `sim_patch/alignment/tests/test_pain_void_original.py`，通过 `PARITY_REPAIRED_ENGINE` 指定修复版目录，在独立进程运行。两个入口分别验证检查器检测能力和修复后的规则，不能把旧版差异测试的期望改成任意引擎自适应。

第五轮在疼痛／虚空修复版本中复现群攻伤害计算时点与鸟面瓮回血顺序差异。8 个原版场景包含 4 个反例和 4 个对照，见[第五轮记录](RESULTS-20260928-ROUND5.md)。以下入口使用修复版，需与加载旧引擎的 `test_native.py` 分进程运行；`test_repaired_native.py` 通过表示检出了第五轮记录的差异，`test_pain_void_original.py` 通过表示第四轮修复行为吻合。

```sh
PARITY_REPAIRED_ENGINE="$PWD/runs/parity-repair-20260927/audit-final/build" \
  "$PARITY_PY" -m unittest sim_patch.parity.tests.test_repaired_native \
  sim_patch.alignment.tests.test_pain_void_original -v
```

[群攻与鸟面瓮修复](REPAIR-20260928-AOE-URN.md)处理第五轮差异，并补充其余四种群攻的原版捕获，总计 12 个场景。旧版检测入口及样本保持原预期；最新修复版使用下面的验收入口，不能把 `test_repaired_native.py` 的负向预期当成最新修复版的通过标准。

```sh
PARITY_REPAIRED_ENGINE="$PWD/runs/parity-repair-20260928/audit/build" \
  "$PARITY_PY" -m unittest sim_patch.alignment.tests.test_aoe_urn_original \
  sim_patch.alignment.tests.test_pain_void_original -v
```

生产构建位于 `runs/parity-repair-20260928/build`，包含重建的 `slaythespire` 与 `fightsim`。`aoe_urn_order.patch` 在 `pain_void_order.patch` 后应用；修复版运行时与旧观察构建使用不同目录，历史证据的引擎身份保留。

第六轮在该修复版中确认消耗牌的能力触发顺序、红头骨与复活的力量结算顺序两类差异。8 个原版场景包含 3 个反例、5 个对照，见[第六轮记录](RESULTS-20260928-ROUND6.md)。检测入口要求这些已记录差异存在，不能用其通过结果表示模拟器完成修复：

```sh
PARITY_ROUND6_ENGINE="$PWD/runs/parity-repair-20260928/audit/build" \
  "$PARITY_PY" -m unittest sim_patch.parity.tests.test_round6_native -v
```

使用 `runs/parity-repair-20260928/build` 可在生产构建复核同一批样本；两种构建须在独立进程加载。第六轮没有修改模拟器规则，既有修复验收入口继续适用。

[消耗牌能力顺序与红头骨修复](REPAIR-20260928-EXHAUST-SKULL.md)处理第六轮差异，补充力量下限、蜥蜴尾巴和人工制品对照；12 个原版场景的被比较字段吻合。新运行时为 `runs/parity-repair-20260928-exhaust-skull/build`，观察构建为同级 `audit/build`，`exhaust_skull_order.patch` 接在 `aoe_urn_order.patch` 后应用。`test_round6_native.py` 保留旧构建的负向检测预期。

[第七轮检查](RESULTS-20260928-ROUND7.md)从该修复版发现抽牌能力顺序、生命上限变化误判红头骨生效状态两类差异，包含 3 个反例和 5 个对照。修复验收与新差异检测可在同一构建中执行：

```sh
PARITY_REPAIRED_ENGINE="$PWD/runs/parity-repair-20260928-exhaust-skull/audit/build" \
PARITY_ROUND7_ENGINE="$PWD/runs/parity-repair-20260928-exhaust-skull/audit/build" \
  "$PARITY_PY" -m unittest sim_patch.alignment.tests.test_exhaust_skull_original \
  sim_patch.alignment.tests.test_aoe_urn_original sim_patch.alignment.tests.test_pain_void_original \
  sim_patch.parity.tests.test_round7_native -v
```

其中 `test_round7_native.py` 通过表示检出第七轮记录中的错误，不表示这些新发现完成修复。

[抽牌与红头骨历史状态修复](REPAIR-20260928-DRAW-SKULL.md)处理第七轮差异，14 个原版场景的被比较字段吻合。新运行时为 `runs/parity-repair-20260928-draw-skull/build`，观察构建为同级 `audit/build`；`draw_skull_state.patch` 接在 `exhaust_skull_order.patch` 后应用。新增历史标记随快照导入，后续动作不回填原版状态；旧引擎未提供的计数字段记为覆盖缺口。

[第八轮检查](RESULTS-20260928-ROUND8.md)确认撕裂复活加力量时机、残暴抽牌与失血顺序两类差异。8 个原版场景包含 4 个反例、4 个对照。当前构建的修复验收与第八轮检测入口如下；第七轮负向测试保留给旧构建使用：

```sh
PARITY_REPAIRED_ENGINE="$PWD/runs/parity-repair-20260928-draw-skull/audit/build" \
PARITY_ROUND8_ENGINE="$PWD/runs/parity-repair-20260928-draw-skull/audit/build" \
  "$PARITY_PY" -m unittest sim_patch.alignment.tests.test_draw_skull_original \
  sim_patch.alignment.tests.test_exhaust_skull_original sim_patch.alignment.tests.test_aoe_urn_original \
  sim_patch.alignment.tests.test_pain_void_original sim_patch.parity.tests.test_round8_native -v
```

两处引擎目录换为生产 `build` 可复核另一构建，需在独立进程加载。15 项测试中，13 项验证修复行为，2 项检测尚存的第八轮差异，不能把检测通过解释为修复通过。虚空结束战斗后的能量由新增原版审计字段单独核对；通用终局比较保留选择界面缺口。

[撕裂与残暴修复](REPAIR-20260928-RUPTURE-BRUTALITY.md)处理第八轮差异，同一批 8 个原版场景的被比较字段吻合。新生产运行时为 `runs/parity-repair-20260928-rupture-brutality/build`，观察构建为同级 `audit/build`；`rupture_brutality_order.patch` 接在 `draw_skull_state.patch` 后应用。第八轮负向检测保留给旧构建使用。

[第九轮检查](RESULTS-20260928-ROUND9.md)找到负力量时突破极限绕过人工制品的一类差异，同时保留四条没有观察到复制暴走差异的场景。当前构建执行 15 项修复验收和 2 项第九轮检测／匹配合同：

```sh
PARITY_REPAIRED_ENGINE="$PWD/runs/parity-repair-20260928-rupture-brutality/audit/build" \
PARITY_ROUND9_ENGINE="$PWD/runs/parity-repair-20260928-rupture-brutality/audit/build" \
  "$PARITY_PY" -m unittest sim_patch.alignment.tests.test_rupture_brutality_original \
  sim_patch.alignment.tests.test_draw_skull_original sim_patch.alignment.tests.test_exhaust_skull_original \
  sim_patch.alignment.tests.test_aoe_urn_original sim_patch.alignment.tests.test_pain_void_original \
  sim_patch.parity.tests.test_round9_native -v
```

两处引擎目录换为生产 `build` 可复核另一构建，需在独立进程加载。第九轮测试通过不表示突破极限问题完成修复。

[突破极限与历史待办修复](REPAIR-20260928-LIMIT-BACKLOG.md)处理五类差异：负力量突破极限、多重暴走、吸血过量回血、旋风斩队列顺序、手动弃牌计数。新运行时为 `runs/parity-repair-20260928-limit-backlog/build`，观察构建为同级 `audit/build`。16 个原版记录的被比较字段吻合，334 个 CTest 入口通过。当前修复验收使用：

```sh
PARITY_REPAIRED_ENGINE="$PWD/runs/parity-repair-20260928-limit-backlog/audit/build" \
  "$PARITY_PY" -m unittest sim_patch.alignment.tests.test_limit_backlog_original \
  sim_patch.alignment.tests.test_rupture_brutality_original sim_patch.alignment.tests.test_draw_skull_original \
  sim_patch.alignment.tests.test_exhaust_skull_original sim_patch.alignment.tests.test_aoe_urn_original \
  sim_patch.alignment.tests.test_pain_void_original -v
```

20 项测试覆盖 70 个原版场景及专项状态核对；生产 Python 绑定缺少弃牌计数字段，该项由观察构建重放与生产 C++ 回归核对。第九轮检测保留给上一版冻结引擎。后续进度和停止条件见[持续排查清单](CONTINUOUS-AUDIT.md)。

[斗技场激怒修复](REPAIR-20260928-COLOSSEUM-ENRAGE.md)处理非首个怪物的漏触发，8 个场景吻合。[虚无牌消耗顺序修复](REPAIR-20260928-ETHEREAL-PROFILES.md)处理 BaseMod 与共享 Java RNG 两种配置及手牌位置变化后的身份查找，8 个场景吻合。当前生产目录为 `runs/parity-repair-20260928-ethereal-profiles/build`，观察构建为同级 `audit/build`。上面命令替换此目录，并添加 `sim_patch.alignment.tests.test_colosseum_enrage_original` 与 `sim_patch.alignment.tests.test_ethereal_profiles_original`，得到 27 项累计修复合同，覆盖 86 个原版场景及专项状态核对。355 个 CTest 入口通过，完整一致性为 `INCOMPLETE`。

`end_turn_shuffle` 保存参考配置、共享随机源初始化标志和 `shared_seed48`。Steam 导出器与两个构建均支持该字段。默认 `basemod_seeded` 对应当前安装的参考环境；`java_shared` 需要观察到的共享状态，不猜初始化种子。缺少此字段的历史捕获保留覆盖缺口，无 Mod 整局随机消费尚未验收。

[特殊回调与免费状态修复](REPAIR-20260928-ETHEREAL-OVERRIDES.md)补齐巩固、幽灵铠甲与指定牌消耗状态。当前生产目录为 `runs/parity-repair-20260928-ethereal-overrides/build`，观察构建为同级 `audit/build`。累计命令添加 `sim_patch.alignment.tests.test_ethereal_overrides_original`，得到 31 项原版验收、97 个场景及专项状态核对；366 个 CTest 入口通过。深度 2 动作树与战斗外原始差异见[检查记录](RESULTS-20260928-ROUND11-OUTSIDE-TREE.md)。

## 报告与状态

[斗技场连续战斗随机状态修复](REPAIR-20260928-COLOSSEUM-RNG.md)保留同一房间两场战斗之间的随机状态，并执行返回事件时的准备牌组随机消耗。当前生产目录为 `runs/parity-repair-20260928-colosseum-rng/build`，观察构建为同级 `audit/build`。累计命令添加 `sim_patch.alignment.tests.test_colosseum_rng_original`，得到 32 项验收、103 个原版场景及状态合同；374 个 CTest 入口通过。专用 `python -m sim_patch.parity.colosseum` 以初态和原版命令独立回放两个战斗入口，字段之外的缺口保留。

### 瓶装遗物选牌顺序

[选牌顺序修复](REPAIR-20260928-BOTTLE-CHOICE.md)对齐三种瓶装遗物的候选牌顺序、选中身份和下一场开局手牌。当前生产目录为 `runs/parity-repair-20260928-bottle-choice/build`，观察构建为同级 `audit/build`。累计命令添加 `sim_patch.alignment.tests.test_bottle_choice_original`，得到 34 项验收、113 个原版场景及状态合同；383 个 CTest 入口通过。原始计数表示差异仍在报告中。历史 `full_chain` 轨迹的瓶装下标按主牌组位置转换，新轨迹记录 `selection_deck_indices`；该处理只改变输入编码，不读取后续原版结果或覆盖模拟器状态。

### 固有牌开局补抽顺序

[补抽顺序修复](REPAIR-20260928-INNATE-OPENING.md)把补抽安排在百科全书的战前生成牌之后。当前生产目录为 `runs/parity-repair-20260928-innate-opening/build`，观察构建为同级 `audit/build`。累计命令添加 `sim_patch.alignment.tests.test_innate_opening_original`，得到 36 项验收、119 个原版场景及状态合同；391 个 CTest 入口通过。6 个本轮原版场景包含异蛇之眼阈值、瓶装牌和扭曲之钳对照，计数表示差异保留。

### 天体仪小牌组变化顺序

[天体仪修复](REPAIR-20260928-ASTROLABE-SMALL.md)以主牌组顺序处理自动变化，修正删除后的候选下标。当前生产目录为 `runs/parity-repair-20260928-astrolabe-small/build`，观察构建为同级 `audit/build`。累计命令添加 `sim_patch.alignment.tests.test_astrolabe_small_original`，得到 38 项验收、127 个原版场景及状态合同；400 个 CTest 入口通过。8 个新验收场景覆盖混合牌池和移除／获得遗物效果，914 个历史战斗外观察步骤在修复前后相同。计数、阶段配对和私有状态缺口保留。

`plan.json` 记录输入和程序哈希，`harness/` 保存运行时检查器源码，`workers/` 保存每例输入及日志，`cases/*.json.gz` 保存比较证据，`reproducers/` 保存首个分歧前缀，`report.json` / `report.md` 给出索引。前缀缩短只表示删掉首个分歧之后的动作，不代表数学上的最小反例。

| 状态 | 含义 |
|---|---|
| `mismatch` | 被映射并比较的字段或操作合法性不同，需结合动作映射核对根因 |
| `import_mismatch` | 起点恢复后出现差异，后续动作不执行 |
| `identity_difference` | 初始建立的原版 UUID 与模拟器实例编号对应关系不再维持；同名牌可能遮住实例顺序差异，需继续验证行为影响 |
| `observation_difference` | 战斗外原始观测不同，保留计数表示和顺序差别，不直接判为规则缺陷 |
| `coverage_gap` | 没有已比较字段的分歧或存在无法执行的选择；缺口阻止完整验收 |
| `original_error` / `adapter_error` / `worker_error` / `timeout` | 原版、适配或执行未完成；不计通过 |

退出码：`1` 表示分歧或执行错误；`2` 表示有覆盖缺口或生成清单；`0` 仅表示请求的非空案例集没有发现差异和缺口。即使有限案例集满足后者，全局 `exhaustive_parity_proven` 也不会变为真。

## 如何接近“所有不一致”

源码清单用于列出待验证规则，不能把案例名字或执行次数换算成分支覆盖。后续工作需要为分支补原版执行探针，为内部状态建立有源码依据的对应关系，扩展 UI 选择与战斗外操作域，遍历有明确边界的种子、状态和输入。每找到首个分歧，应先确认输入对应关系，再修复或隔离根因后重跑，以揭示被首个分歧遮住的后续问题。

当前还缺完整的动态分支覆盖、所有私有字段对应、UI 选择合法域、全部怪物/遗物组合、高阶交互、无界动作序列，以及对所有原版运行时模组和不同帧节奏的独立验证。未知范围保留为未知，不能用“现有测试全部通过”替代。

## 昆虫标本生命上限与入战配对

[昆虫标本修复](REPAIR-20260928-PRESERVED-INSECT.md)保留涅奥和先前遗物造成的降血。当前生产目录为 `runs/parity-repair-20260928-preserved-insect/build`，观察构建为同级 `audit/build`。累计命令添加 `sim_patch.alignment.tests.test_preserved_insect_original`、`test_event_entry_original` 和 `test_save_entry_original`，得到 42 项验收、182 个场景及状态合同；411 个 CTest 入口通过。新增 8 个修复场景和 [47 个事件／存档入战场景](RESULTS-20260928-EVENT-SAVE-ENTRY.md)，后者把初态和战斗观察阶段配对。914 个历史样本的原始步骤与旧运行时相同，计数和私有状态缺口保留。

## 遗物计数生命周期

[计数修复](REPAIR-20260928-RELIC-COUNTERS.md)处理小花／香炉的 −1 恢复边界和哀嚎的耗尽标记。当前生产目录为 `runs/parity-repair-20260928-relic-counters/build`，观察构建为同级 `audit/build`。累计命令添加 `sim_patch.alignment.tests.test_relic_counters_original`，得到 44 项验收、195 个场景及状态合同；424 个 CTest 入口通过。13 个新原版场景记录 19 个初始阶段与 58 个检查点，7 个行为／持久计数反例消失。茶具／哀嚎的战斗内原始计数差异保留，检查器拒绝把任意计数差异归入延迟写回。

## 遗物默认计数

[默认计数修复](REPAIR-20260928-RELIC-DEFAULTS.md)把遗物获得／替换的默认值改为原版的 −1，保留显式零初始化。当前生产目录为 `runs/parity-repair-20260928-relic-defaults/build`，观察构建为同级 `audit/build`。累计命令添加 `sim_patch.alignment.tests.test_relic_defaults_original`，得到 46 项验收、210 个场景及状态合同；435 个 CTest 入口通过。15 个新原版场景记录 57 个初始／获得阶段、67 个检查点，9 个反例消失，战斗内原始计数差异保留。原版 `SaveFile` 字段参与比较，但没有验证写盘重载。NN 计数输入随修复变化，旧模型胜率未重测。下一批检查自然事件胜利及奖励领取。[冻结运行时](../../runs/parity-repair-20260928-relic-defaults/runtime.json)

## 事件奖励后续

[事件奖励检查](RESULTS-20260928-EVENT-REWARDS.md)使用同一规则源码，增加独立 `event_rewards_probe` 与 `test_event_rewards_original`。新增 CTest 入口通过；单独运行测试时设置 `PARITY_EVENT_REWARDS_EXECUTABLE` 指向观察器。26 个场景、157 个检查点验证胜利、奖励生成、领取与离开；10 个反例验证检查器拒绝错误状态。累计合同包含 236 个场景及状态合同，本轮没有重跑完整 CTest。战斗内原始计数和死亡 Boss 空槽表示差异保留；下一项是遗物奖励选牌后返回剩余奖励。[观察器清单](../../runs/parity-20260928/round25-event-rewards-tools/runtime.json)

[奖励选牌检查](RESULTS-20260928-REWARD-SELECTION.md)补充 12 个原版场景、93 个检查点，核对瓶装选牌与剩余奖励、复制状态、歌唱碗及卡牌界面关闭后重新打开。行为字段吻合，24 处哀嚎原始计数差异保留；9 个负对照被拒绝。新增 `test_reward_selection_original` 复用 `PARITY_EVENT_REWARDS_EXECUTABLE`；本轮 3 个 CTest 入口、6 项测试方法通过，累计合同包含 248 个场景及状态合同。规则核心没有改动，下一项为宝箱钥匙与遗物的关联。[观察器清单](../../runs/parity-20260928/round26-reward-selection-tools/runtime.json)

[宝箱检查](RESULTS-20260928-TREASURE.md)增加 17 个原版场景、95 个检查点，核对套娃、蓝宝石钥匙关联、面具、瓶装返回、诅咒钥匙与领取副作用。新增 `treasure_probe`、`test_treasure_original`；单独运行设置 `PARITY_TREASURE_EXECUTABLE`。12 个负对照被拒绝，4 个 CTest 入口、8 项测试方法通过，累计合同包含 265 个场景及状态合同。36 处跨类型奖励排列差异保留，规则核心没有改动。[观察器清单](../../runs/parity-20260928/round27-treasure-tools/runtime.json)

[商店选牌返回修复](REPAIR-20260928-SHOP-REWARDS.md)补充 19 个原版场景、116 个检查点。星系仪留下奖励后购买瓶装遗物，选牌结束应恢复剩余奖励；修复同时限定奖励缓存的房间生命周期。447 个 CTest 入口通过，14 个负对照被拒绝，累计合同覆盖 284 个场景及状态合同。`shop_rewards.patch` 接在 `relic_defaults.patch` 后。[运行时](../../runs/parity-repair-20260928-shop-rewards/runtime.json)包含生产、观察和搜索模块；完整 UI、共享表现 RNG 与自然整局覆盖保留缺口。

[商店删牌结算修复](REPAIR-20260928-SHOP-PURGE.md)补充 24 个原版场景、127 个检查点。星系仪留下奖励时，删牌确认先返回奖励页，回到商店才扣款与移除卡牌。四个反例修复，九处药水动作域差异保留；456 个 CTest 入口通过，22 个错误状态与四个边界输入被拒绝，累计合同覆盖 308 个场景及状态合同。`shop_purge.patch` 接在 `shop_rewards.patch` 后，[运行时](../../runs/parity-repair-20260928-shop-purge/runtime.json)保留生产、观察和搜索模块。下一项检查有色牌补货的共享 RNG。

[商店共享 RNG 修复](REPAIR-20260928-SHOP-SHARED-RNG.md)增加一次性界面初态输入与声明帧时序的 native 入口，按原版顺序推进漂浮、对话及文字渲染随机消费。14 个场景、58 个检查点消除 122 处规则字段分歧；457 个 CTest 入口通过，累计 322 个场景及状态合同。生产目录为 `runs/parity-repair-20260928-shop-shared-rng/production-build`；[运行时](../../runs/parity-repair-20260928-shop-shared-rng/runtime.json)保留生产、观察和搜索模块。默认未附加界面状态的路径不能提供精确共享 RNG 保证；药水、瓶装遗物及添水点击后的三个分歧进入下一轮。

[非购卡商店共享 RNG 修复](REPAIR-20260928-SHOP-OTHER-RNG.md)支持药水、瓶装选牌、蛋类与会员卡的声明帧连续操作，包含闲聊重启和抖动文字。18 场景、87 检查点，458 个 CTest 入口通过；累计 340 个场景及状态合同。生产目录 `runs/parity-repair-20260928-shop-other-rng/production-build`，[运行时](../../runs/parity-repair-20260928-shop-other-rng/runtime.json)绑定规则源码、生产、观察和搜索模块。删牌确认／取消后的三个原版分歧进入下一轮；完整一致性为 `INCOMPLETE`。

[删牌与共享 RNG 修复](REPAIR-20260928-SHOP-PURGE-RNG.md)增加删牌确认／取消、光效寿命及第一幕离店背景的声明帧推进。23 场景、124 检查点，459 个 CTest 入口通过；累计 363 个场景及状态合同。生产目录 `runs/parity-repair-20260928-shop-purge-rng/production-build`，[运行时](../../runs/parity-repair-20260928-shop-purge-rng/runtime.json)绑定规则源码、生产、观察和搜索模块。星系仪／药水鼎奖励返回后的三个补货反例进入下一轮，完整一致性为 `INCOMPLETE`。

[商店奖励与共享 RNG 修复](REPAIR-20260928-SHOP-REWARD-RNG.md)支持药水鼎／星系仪的奖励领取、提示列表和共享 Collections 状态、歌唱碗回血、药水闪光及返回商店交互。22 场景、190 检查点消除 381 处规则字段差异；460 个 CTest 入口通过，累计 385 个场景及状态合同。23 处药水点击选项差异保留。生产目录 `runs/parity-repair-20260928-shop-reward-rng/production-build`，[运行时](../../runs/parity-repair-20260928-shop-reward-rng/runtime.json)绑定规则源码、生产、观察和搜索模块。本轮验收后按用户要求暂停，下一轮源码候选没有执行原版捕获，完整一致性为 `INCOMPLETE`。

[商店回血与复制效果修复](REPAIR-20260929-SHOP-OBTAIN-RNG.md)补齐华夫饼与水果的回血表现、多利之镜的延迟获得和共享 RNG 顺序。23 场景、120 检查点消除 236 处规则字段差异；生产与观察构建的比较字段吻合。461 个 CTest 入口完成验证；首次测试选牌错误、补充原版场景和单项重跑记录保留，累计 408 个场景及状态合同。生产目录 `runs/parity-repair-20260929-shop-obtain-rng/production-build`，[运行时](../../runs/parity-repair-20260929-shop-obtain-rng/runtime.json)绑定源码和构建。本轮验收后按用户要求暂停，下一轮排查没有启动，完整一致性为 `INCOMPLETE`。

[升级遗物与共享 RNG 修复](REPAIR-20260929-SHOP-UPGRADE-RNG.md)增加 `installed-shop-v6` 与 `UPGRADE` 时钟，支持磨刀石、战纹的升级动画和后续商店操作。20 个原版场景、109 个检查点；462 个 CTest 入口通过，累计 428 个场景及状态合同。生产目录 `runs/parity-repair-20260929-shop-upgrade-rng/production-build`，[运行时](../../runs/parity-repair-20260929-shop-upgrade-rng/runtime.json)绑定源码、构建和证据。本轮按用户要求暂停，下一轮排查没有启动，完整一致性为 `INCOMPLETE`。


[获得卡牌回调修复](REPAIR-20260929-CARD-OBTAIN-CALLBACKS.md)复用 v5/v6 界面状态，在原版对应的顶层或普通效果阶段触发遗物回调，处理御守抵消。18 个场景、95 个检查点；463 个 CTest 入口通过，累计 446 个场景及状态合同。生产目录 `runs/parity-repair-20260929-card-obtain-callbacks/production-build`，[运行时](../../runs/parity-repair-20260929-card-obtain-callbacks/runtime.json)绑定源码、构建和证据。用户撤销暂停要求，新 goal 为 active；完整一致性为 `INCOMPLETE`。


[商店点击动作域修复](REPAIR-20260929-SHOP-CLICK-DOMAIN.md)增加 `get_shop_clicks` 与动作上的 `is_valid_shop_click`／`execute_shop_click`，用于重放原版商店命令。旧搜索接口过滤不能购买的药水点击。8 个新原版场景及 64 个历史场景比较字段吻合；464 个 CTest 入口验证完成，首轮 462 个通过，两项测试修正后复测通过。累计 454 个场景及状态合同；[运行时](../../runs/parity-repair-20260929-shop-click-domain/runtime.json)，完整一致性为 `INCOMPLETE`，goal 为 active。

[满背包药水奖励点击](REPAIR-20260929-REWARD-CLICK-DOMAIN.md)增加 `claim_potion_reward`，用于执行搜索器过滤的原版点击。10 个场景、70 个检查点吻合；7 个受阻路径获得覆盖，3 个对照保留。465 个 CTest 入口验证完成，首轮 464 个通过，新夹具经两次修正后定向复测通过。累计 464 个场景及状态合同；[运行时](../../runs/parity-repair-20260929-reward-click-domain/runtime.json)，完整一致性为 `INCOMPLETE`，goal 为 active。

[掉血抽牌遗物顺序修复](REPAIR-20260929-HP-LOSS-RELIC-ORDER.md)让整局入战与快照导入保留百年积木／符文立方体的获得顺序。10 个原版场景、42 个检查点吻合，3 个能量／后续伤害反例消除。467 个 CTest 入口首轮通过，累计 474 个场景及状态合同；[运行时](../../runs/parity-repair-20260929-hp-loss-relic-order/runtime.json)，完整一致性为 `INCOMPLETE`，goal 为 active。

[百年积木恢复状态修复](REPAIR-20260929-CENTENNIAL-RESTORE.md)导出并保留本场触发状态，受伤后缺少字段的快照拒绝导入。六个原版场景衍生 26 个恢复合同、70 个后续动作，消除 6 个差异合同。468 个 CTest 入口验证完成，首轮 467 个通过，一项历史缺失状态合同经明确分类后定向复测通过。累计 480 个场景及状态合同；[运行时](../../runs/parity-repair-20260929-centennial-restore/runtime.json)，完整一致性为 `INCOMPLETE`，goal 为 active。

[发掘选牌修复](REPAIR-20260929-EXHUME-SELECTION.md)保留单候选但多张消耗牌时的选择步骤，并按原版暂存、归还其他发掘牌。十个原版场景、46 个检查点、8 个选择边界消除 7 个反例。469 个 CTest 入口首轮通过，累计 490 个场景及状态合同；[运行时](../../runs/parity-repair-20260929-exhume-selection/runtime.json)，完整一致性为 `INCOMPLETE`，goal 为 active。

[持续排查停止记录](RESULTS-20260929-AUDIT-CLOSE.md)：R18 至 R23 六项修复／接口补全通过验收，交付沿用 R23。后续 18 个探索场景没有建立新的待修可达规则反例；人工输入差异与界面表示边界保留，候选费用补丁没有采纳。本次有限 goal 达到停止条件，完整一致性为 `INCOMPLETE`。

[升级开悟免费效果修复](REPAIR-20260930-ENLIGHTENMENT-FREE.md)补充木乃伊之手和液态记忆产生的可达反例：五个费用分歧消除，九个原版场景的比较字段吻合。生产／观察／搜索运行时与 470 个回归入口、六个邻近升级探索场景的证据见修复报告，完整一致性状态为 INCOMPLETE。

[生成牌 X 费用修复](REPAIR-20260930-GENERATED-X-COST.md)保留羽化生成旋风斩时的 X 费用；七个原版场景、75 个检查点消除五个反例，包含出牌、异蛇油和化学 X 后续。471 个回归入口通过；修复后四个邻近生成效果场景的比较字段吻合，完整一致性状态为 INCOMPLETE。

[自动出牌消耗与复制顺序修复](REPAIR-20260930-AUTOPLAY-EXHAUST.md)解决受限出牌丢失消耗属性、时间吞噬者清理读取上一张牌、复制牌落在后续自动出牌之后的三处规则差异。18 个原版场景、163 个检查点消除 12 个反例；472 个最终回归入口通过，累计场景及状态合同为 524。修复后的四个邻近场景比较字段吻合，完整一致性状态为 INCOMPLETE。

[医疗箱／蓝蜡烛消耗标记修复](REPAIR-20260930-PERSISTENT-EXHAUST.md)覆盖奇怪的勺子保留牌后的结束回合移牌、分支复制和中途恢复。12 个原版场景消除七个反例，86 条动作、98 个检查点吻合；八个恢复位置、四个负对照和 473 个回归入口通过。修复后九个原版邻近场景的比较字段和逐牌消耗属性吻合。累计场景及状态合同为 536，完整一致性为 INCOMPLETE；[运行时](../../runs/parity-repair-20260930-persistent-exhaust/runtime.json)。
