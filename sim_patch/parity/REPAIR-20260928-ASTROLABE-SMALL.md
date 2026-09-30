# 2026-09-28 天体仪小牌组变化顺序修复

天体仪在可变化的牌不超过三张时会自动处理这些牌。模拟器按相反顺序处理，把同一串随机数分配给了不同的变化牌池，导致结果不同。原有基础牌样本来自同一个变化池，没有暴露这个错误；加入无色牌和诅咒后出现反例。

## 原版证据与根因

原版 `Astrolabe.onEquip` 用 `getPurgeableCards` 建立候选，再调用 `addToTop`。这里的 `addToTop` 在列表尾部追加，因此候选保持主牌组顺序。`giveCards` 按这个顺序移除旧牌、生成新牌，并排队执行获得牌效果。旧模拟器为了避免删除引起下标移动，倒序执行了整个循环。[源码核对](../../runs/parity-repair-20260928-astrolabe-small/source-audit.json)。

第一组原版反例的候选顺序为寄生、妙计、撕咬。按捕获中的卡牌 ID，原版得到 `Doubt`、`Jack Of All Trades+`、`Panache+`；模拟器得到 `PanicButton+`、`Jack Of All Trades+`、`Regret`。随机状态相同不代表生成结果相同，因为处理每张牌时使用的变化池不同。

本轮复用 4 个第十八轮原版捕获，并增加 4 个独立 JVM 检查移除／获得牌效果。新增样本覆盖黑石护符、陶瓷小鱼、鲜血神像、御守、两张寄生和瓶装牌。[变化顺序输入](specs/astrolabe_small_round18.json)、[遗物效果输入](specs/astrolabe_lifecycle_round19.json)、[顺序捕获](tests/fixtures/astrolabe-small-original.json.gz)、[效果捕获](tests/fixtures/astrolabe-lifecycle-original.json.gz)、[来源与清理](tests/fixtures/provenance.json)。后续原版状态只参与比较。

## 修改与验证

[补丁](../astrolabe_small.patch)接在 `innate_opening.patch` 后，修改 `GameContext.cpp` 的小牌组处理分支。循环按原版候选顺序执行，用“原牌组下标减去前面删除的数量”找到当前牌。旧牌移除及变化顺序保持一致，新牌获得留在循环之后；手动选牌路径不经过该分支。

| 验证 | 结果 |
|---|---|
| 8 个原版场景 | 4 个变化结果反例消失，4 个对照吻合；生产、观察构建均核对牌组顺序及升级、生命、生命上限、金币、遗物状态、瓶装标志和 RNG |
| 原始计数表示 | 8 个场景保留天体仪 `counter=-1` 对 `data=0`，报告为 `observation_difference`，不计为完整观察通过 |
| 8 个 C++ 专项 | 旧核心 4 失败、4 对照通过；新核心 8 通过，包含不可移除牌夹在候选中、空候选／单候选、手动选择与复制隔离 |
| 全部 CTest | 400 个入口通过，含历史自然整局及输入身份合同 |
| 累计原版修复合同 | 生产、观察构建各 38 项测试通过，累计覆盖 127 个原版场景及状态合同 |
| 既有战斗外 914 样本 | 前后完整比较步骤相同；597 个 `coverage_gap`、317 个 `observation_difference` 保留 |
| 检查器反例 | 冻结旧引擎的 41 项测试通过 |
| 可移植补丁与搜索模块 | 两套源码零 fuzz 应用，两个变更翻译单元语法检查通过；搜索重编，8 个顺序／批量任务及源状态、复制隔离通过 |

[顺序修复前比较](../../runs/parity-20260928/round18-astrolabe-small-v1/comparison/report.json)、[遗物效果修复前比较](../../runs/parity-20260928/round19-astrolabe-lifecycle-v1/comparison/report.json)、[生产比较](../../runs/parity-repair-20260928-astrolabe-small/replay-production/report.json)、[观察构建比较](../../runs/parity-repair-20260928-astrolabe-small/replay-audit/report.json)、[差异分类](../../runs/parity-repair-20260928-astrolabe-small/classification.json)。

[专项前后对照](../../runs/parity-repair-20260928-astrolabe-small/focused-before-after.json)、[回归日志](../../runs/parity-repair-20260928-astrolabe-small/ctest.log)、[914 样本完整步骤比较](../../runs/parity-repair-20260928-astrolabe-small/existing-outside-comparison.json)。基础牌对照通过只能说明这些输入没有变化，不能证明混合牌池顺序正确。

当前生产目录为 `runs/parity-repair-20260928-astrolabe-small/build`，观察构建为同级 `audit/build`。[分发清单](../alignment/astrolabe-small-manifest.json)、[源码及运行时身份](../../runs/parity-repair-20260928-astrolabe-small/runtime.json)、[交付核验](../../runs/parity-repair-20260928-astrolabe-small/verification.json)。上轮修复源码与二进制保留。

```bash
python -m sim_patch.parity outside \
  --engine runs/parity-repair-20260928-astrolabe-small/build \
  --executable runs/parity-repair-20260928-astrolabe-small/build/outside_probe \
  --source sim_patch/parity/tests/fixtures/astrolabe-small-original.json.gz \
  --source sim_patch/parity/tests/fixtures/astrolabe-lifecycle-original.json.gz \
  --out runs/astrolabe-small-replay-new-directory
```

证据限于安装的 Mod 原版、这些输入及稳定观察点。未比较的私有状态、全部动作域、无 Mod 原版和完整动态分支保留缺口，一致性结论为 `INCOMPLETE`。8 个原版实例退出，没有提交、推送或修改主工作树。goal 为 active；战斗外阶段配对和其他交互的待办保留在[持续排查清单](CONTINUOUS-AUDIT.md)。
