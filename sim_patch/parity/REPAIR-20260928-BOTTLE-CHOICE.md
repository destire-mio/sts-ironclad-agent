# 2026-09-28 瓶装遗物选牌顺序修复

瓶装火焰、瓶装闪电、瓶装旋风的候选牌顺序与原版相反。同样选择第 0 项，两边会瓶装不同的牌，下一场的开局手牌也会变化。修复统一了候选顺序，并保留重复牌、升级牌的牌组身份。

## 原版证据与根因

三个遗物的 `onEquip` 都调用 `getPurgeableCards` 后按类型筛选。前者保留主牌组顺序，后者在遍历时调用 `addToBottom`，把每张匹配牌插到第 0 项，因此候选顺序反转。模拟器的 `addMatchingToSelectList` 保留主牌组顺序，造成差异。[源码记录](../../runs/parity-repair-20260928-bottle-choice/source-audit.json)。

本轮在 10 个独立原版 JVM 中捕获三个遗物的候选列表、选中后的瓶装标志和下一场开局手牌，包含重复牌、升级牌、单候选和空候选。[输入](specs/bottle_choice_round16.json)、[不可变原版捕获](tests/fixtures/bottle-choice-original.json.gz)、[来源及实例清理](tests/fixtures/provenance.json)。

旧观察器把战斗手牌的瓶装标志写为 `false`。本轮根据开局牌的主牌组身份读取瓶装状态；同一份观察器分别链接旧核心和新核心，避免把观察器修正算作规则修复。新旧观察器的捕获比较保留，规则前后对照使用同一份新观察器。原版起始主牌组、遗物池和初始物品用于配对输入，选牌之后没有导入原版状态。

## 修改与验证

[规则补丁](../bottle_choice.patch)接在 `colosseum_rng.patch` 后，在瓶装遗物收集候选牌之后反转列表。普通升级、移除等选牌路径不经过该反转。

修复使历史模拟器动作下标改变了含义。历史自然轨迹第 40 层原来用下标 0 表示主牌组第 10 张腐化；新候选顺序中这张牌位于下标 3。回放器按照记录时的候选牌组位置翻译输入下标，再通过原版 UUID 寻找同一张牌，并检查不可变原版记录中的命令。第 43 层的另一次瓶装选择采用相同处理。新生成的轨迹记录候选牌组位置，避免依赖版本中的列表顺序；原始捕获没有改写。

| 验证 | 结果 |
|---|---|
| 10 个原版场景 | 修复前 7 个选牌规则反例、3 个对照；生产与观察构建修复后，候选列表、瓶装身份及开局手牌吻合 |
| 原始计数差异 | 10 个场景保留遗物 `counter=-1` 对 `data=0` 的差异，报告为 `observation_difference`，不计为完整观察通过 |
| 7 个 C++ 专项 | 同输入链接旧核心得到 3 失败、4 对照通过；新核心 7 通过，含分支复制、升级牌和非瓶装选择对照 |
| 全部 CTest | 383 个入口通过；首次 382 项中的历史下标回归失败日志保留 |
| 累计原版修复合同 | 生产、观察构建各 34 项测试通过，累计覆盖 113 个原版场景及状态合同 |
| 历史自然整局 | 1002 条原版命令、909 个比较点重放，终点第 51 层失败、得分 1786；没有重新导入状态 |
| 轨迹身份合同 | 5 项测试通过；错误选牌及损坏候选身份会失败，C++／Python 转换后的输入能够重放相同原版记录 |
| 检查器反例 | 冻结旧引擎的 41 项测试通过 |
| 补丁及搜索运行时 | 两套源码零 fuzz 应用，两个变更翻译单元语法检查通过；搜索模块重编，8 个顺序／批量任务结果及分支隔离通过 |

[同观察器旧核心比较](../../runs/parity-repair-20260928-bottle-choice/replay-before/report.json)、[生产比较](../../runs/parity-repair-20260928-bottle-choice/replay-production/report.json)、[观察构建比较](../../runs/parity-repair-20260928-bottle-choice/replay-audit/report.json)、[差异分类](../../runs/parity-repair-20260928-bottle-choice/classification.json)、[原始观察器比较](../../runs/parity-20260928/round16-bottle-choice-v1/comparison/report.json)。

[专项前后对照](../../runs/parity-repair-20260928-bottle-choice/focused-before-after.json)、[回归日志](../../runs/parity-repair-20260928-bottle-choice/ctest.log)、[首次回归日志](../../runs/parity-repair-20260928-bottle-choice/ctest-attempt1.log)、[身份合同](../../runs/parity-repair-20260928-bottle-choice/trace-selection-contract.log)、[自然整局比较](../../runs/parity-repair-20260928-bottle-choice/natural-audit/report.json)。

运行时入口为 `runs/parity-repair-20260928-bottle-choice/build`，观察构建为同级 `audit/build`。[分发清单](../alignment/bottle-choice-manifest.json)、[源码与二进制身份](../../runs/parity-repair-20260928-bottle-choice/runtime.json)、[交付核验](../../runs/parity-repair-20260928-bottle-choice/verification.json)。

```bash
python -m sim_patch.parity outside \
  --engine runs/parity-repair-20260928-bottle-choice/build \
  --executable runs/parity-repair-20260928-bottle-choice/build/outside_probe \
  --source sim_patch/parity/tests/fixtures/bottle-choice-original.json.gz \
  --out runs/bottle-choice-replay-new-directory
```

结果限于安装的 Mod 原版配置和记录中的选择。计数表示、全部私有状态、无 Mod 原版和完整动态分支保留缺口，完整一致性为 `INCOMPLETE`。后续检查沿瓶装牌筛选、移除与入战路径推进，见[持续排查清单](CONTINUOUS-AUDIT.md)。goal 为 active；10 个原版实例退出，没有提交、推送或修改主工作树。
