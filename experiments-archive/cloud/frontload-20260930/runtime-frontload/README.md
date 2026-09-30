combat4r 双端战斗运行包

入口：C.F.resolve_combat4r(gc, budget, boss_multiplier)。参数名 game、simulations、boss_multiplier，默认 40000、12.0。核心与 fightsim 配套使用；P300_RUNTIME 指向本目录。

combat4q 搜索逻辑及药水处理，加 30 份模拟器增量补丁和 Nemesis A18 灼伤阈值修复。胜局每获得 1 点最大 HP 加 100 分，等价于额外 1 点当前 HP；当前 HP 项使用胜利遗物结算后的真实 HP，覆盖带骨肉、燃烧之血、黑暗之血、圣职者面具、魔法花、绽放印记与上限截断。HP 投影与实际胜利结算共用纯函数，不生成奖励或推进 RNG。只计本场增长，基准跨重新规划保留。逃跑、死亡和截断沿用原评分。权重代表跨战斗价值的启发式假设，整局收益由用户的 2000 局检验。

保留旧搜索入口；这些入口在本包中使用修复后的机制，原 combat4q 的双模块是旧版对照。源码在上级 engine-source/ 和 agent/。combat4r-build.json 保存平台构建命令和源码/二进制哈希，parent-combat4q-provenance 为父版本资料。

验证与每项移植来源见上级 report.md、evidence/ 和 snapshot-manifest.json。固定状态验证不代表完整原版一致性或整局胜率提升。
