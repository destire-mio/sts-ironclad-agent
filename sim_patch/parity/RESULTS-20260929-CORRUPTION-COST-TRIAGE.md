# 腐化费用候选的排除与边界

此轮没有修改验收运行时，沿用 [R23 发掘修复](REPAIR-20260929-EXHUME-SELECTION.md)。14 个独立原版实例完成取证和收尾：10 个结果为比较字段吻合的 `coverage_gap`，4 个结果为 `mismatch`。四个差异保留原始分类，没有改称通过。

第一组四个场景检查腐化后的秘密技法取牌、单选／多选、无腐化与发掘对照，比较字段吻合。`ApplyPowerAction` 在构造时调整手牌、抽牌堆、弃牌堆和消耗堆的技能费用，所以此前“取牌时未同步费用”的假设没有得到这些原版操作支持。

四个差异来自人工把 `cost_for_turn` 设为高于 `base_cost` 的夹具。原版的 `modifyCostForCombat(-9)` 和模拟器的基础费用判定在此输入上不同；这是真实的低层函数输入差异，但该输入在所需原版玩法中的可达性未建立。场景名中的 `snecko` 是构造时的假说标签，不能当作触发来源证据。

两个异蛇之眼抽牌场景和两个喝异蛇油后打出腐化的场景比较字段吻合。`ConfusionPower` 和 `RandomizeHandCostAction` 都把基础费用与本回合费用写为随机值，因此“基础零费、临时三费”不能由这两个操作来解释。此前对这两条触发路径的描述有误。费用写入点索引和源码核对记录支持这个排除结论；索引不构成对全部可达状态的形式化证明。

`parity-repair-20260929-corruption-zero-base` 中的修改、构建和诊断是未采纳的尝试。候选测试含未经验证的费用假设，没有注册 CTest、没有运行完整回归，文件移到尝试目录保存；没有发布补丁或改变验收运行时。缺少可达证据的四个输入差异保留为覆盖边界，不计入游戏缺陷修复或新增验收合同。

[分类与原版证据](../../runs/parity-20260929/round42-corruption-move-tools/classification.json)、[源码核对](../../runs/parity-20260929/round42-corruption-move-tools/source-audit.json)、[费用写入索引](../../runs/parity-20260929/round42-corruption-move-tools/cost-writes.json)和[未验收说明](../../runs/parity-repair-20260929-corruption-zero-base/UNACCEPTED.md)提供复查入口。完整一致性状态保持 `INCOMPLETE`，goal 为 active；下一项检查手牌选择与确认阶段。
