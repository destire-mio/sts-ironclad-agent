# 2026-09-28 战斗外差异归因与动作树检查

使用虚无牌参考配置修复后的观察构建刷新 914 个战斗外历史样本，得到 597 个 `coverage_gap`、317 个 `observation_difference`。场景名、状态和原始差异与第十轮相同。[刷新报告](../../runs/parity-20260928/round11-outside-v1/report.json)、[前后报告核对](../../runs/parity-20260928/round11-outside-analysis/refresh.json)绑定输入和构建身份。这里使用的引擎为 `ethereal-profiles`，没有把后续 `ethereal-overrides` 构建冒充为这次执行。

| 原始差异 | 归因证据与边界 |
|---|---|
| 266 个遗物计数场景 | 原版值为 `-1`，模拟器内部存储值为 `0`，涉及 131 个遗物 ID。原版 `AbstractRelic.counter` 默认 `-1`；内部存储与显示计数不能直接视为同义。源码映射建立，逐项生命周期仍有缺口 |
| 4 个入战遗物计数场景 | 茶具、开心小花、香炉、涅奥的哀嚎：原版读入战后的遗物；native 输出整局对象的字段，部分状态归战斗对象持有、战后回写。不能据此判断遗物效果失效 |
| 47 个洗牌随机状态场景 | 每个原版值都等于 native 输出值进行一次随机推进后的状态，计数也相差 1。事件进入战斗和读取战斗存档的原版样本执行了初始化；native 观察器在这些路径输出 `GameContext`，未构造对应战斗。起点与阶段配对仍需补足 |
| 1 个瓶装火焰候选顺序场景 | 与遗物计数场景重叠。候选集合相同，位置不同；已有按牌身份选择的对照不能证明任意下标映射正确，顺序差异保留 |

[分类记录](../../runs/parity-20260928/round11-outside-analysis/classification.json)保留全部差异及来源；[135 个遗物的源码映射](../../runs/parity-20260928/round11-outside-analysis/relic-source-map.json)记录文件哈希。没有排序候选牌、删除计数或重新同步 RNG 来把这些场景计成通过。47 个样本的一步推进吻合属于归因证据，不能替代相同初态和动作链的回放。

动作树以“一张打击、1 点能量”的相同夹具启动，枚举原版给出的合法动作到深度 2，节点上限 32。10 个前缀在独立原版 JVM 中执行完毕，被比较字段吻合；深度 2 范围内没有遗留队列，7 个叶节点仍有后续动作，记录为深度边界。[树与比较报告](../../runs/parity-20260928/round11-tree-depth2-v1/report.json)、[边界记录](../../runs/parity-20260928/round11-tree-depth2-v1/tree.json)、[实例清理](../../runs/parity-20260928/round11-tree-cleanup.json)。这不是全部战斗动作序列的覆盖证明。

本轮源码核对排除了两条候选：双重打击在出牌时固定两次伤害，手钻把易伤放入队尾，与当前模拟器对应；飞剑回旋的原版动作每次选定目标后重新计算伤害，因此动态计算本身不是缺陷证据。哨卫原版把能量放入队首，native 的队尾注释失实，本轮未建立其可观察反例。

费用重置候选也完成原版核对：开悟配合恶魔之焰、开悟配合坚毅，以及没有开悟的对照，共 3 个场景被比较字段吻合。`CardGroup.moveToExhaustPile` 没有重置费用，但它创建的 `ExhaustCardEffect` 在动画结束时执行 `resetAttributes`。[原版报告](../../runs/parity-20260928/round14-exhaust-cost-v1/report.json)与[捕获来源](tests/fixtures/provenance.json)保留这个反证；结论限于稳定观察点，不证明动画中间状态一致。

goal 仍为 active。[持续排查清单](CONTINUOUS-AUDIT.md)保留战斗外观察阶段、选择映射与源码交互范围。以上结果不覆盖无 Mod 原版、全部私有字段或无界路径。
