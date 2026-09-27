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

所有运行目录必须是新目录，防止覆盖旧证据。`--case-timeout` 约束单个 native 案例；原版 RPC 有独立超时。自然整局未采用逐案例子进程，进程级挂起/崩溃隔离是它的剩余缺口。

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
PARITY_TEST_ENGINE="$PARITY_ENGINE" "$PARITY_PY" -m unittest discover -s sim_patch/parity/tests -v
```

测试包括伤害、随机数、顺序、可用动作、新增未知字段、空轨迹、未知命令、进程退出与超时，以及本次原版捕获的赌徒药水计数差异。最后一类测试针对冻结版本的已知发现；修复模拟器后，应复核该发现的预期分类，不能修改原版证据让错误版本通过。

第二轮补充暴走与两种复制效果叠加的伤害反例、单种复制效果对照、遇到前序分歧后发现新的伤害差异、战斗与战后状态归属，以及对照端补丁移除的隔离测试。结果见 [第二轮记录](RESULTS-20260927-ROUND2.md)。

第三轮检查带壳寄生怪的致命吸血与复活、旋风斩与精致折扇的荆棘结算顺序。结果及对照见 [第三轮记录](RESULTS-20260927-ROUND3.md)。

## 报告与状态

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
