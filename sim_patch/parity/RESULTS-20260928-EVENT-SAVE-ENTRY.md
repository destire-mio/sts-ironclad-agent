# 事件与存档的入战观察阶段配对

旧 914 样本中的 47 个洗牌状态差异来自两类入口：40 个事件、7 个存档。旧观察器在这些路径读取整局 `GameContext`，原版采样点却完成了战斗开局；旧事件夹具还把洗牌流重置为 seed 123，native 正常开局使用 seed + floor。只补一次随机推进无法证明状态配对，也不能作为模拟器修复。

新的事件夹具在事件构造前声明种子、楼层、生命、牌组、遗物及随机流。两边独立从这些初态执行；九组 RNG 的状态字与计数、牌组及遗物身份先作初态核对。原版通过普通 `choose` 命令入战，native 通过事件操作构造 `BattleContext`。比较开局和一次 `end` 之后的状态，不导入原版后续状态。亡者冒险家和神秘球体的确认页面属于 UI 步骤，原始命令保留；本轮不宣称 UI 页面逐步对应。

新的存档场景把同一份捕获的编码存档交给原版加载器与 native 加载器，在两个稳定战斗决策点比较。存档输入按内容哈希绑定。没有把原版加载后的随机数、怪物或手牌写回模拟器。

| 场景 | 数量 | 比较结果 |
|---|---:|---|
| 亡者冒险家 | 26 | 初态及两个战斗决策点的比较字段吻合 |
| 强盗 | 4 | 同上 |
| 神秘球体、心灵绽放 | 3 + 3 | 同上 |
| 蘑菇 | 4 | 同上 |
| 普通、精英、Boss、第三幕双 Boss、第四幕加载 | 7 | 同一存档输入，加载开局及第一回合结束后的比较字段吻合 |

比较范围为九组 RNG 的状态字及计数、有序手牌与各牌堆、费用、生命、能量、格挡、八种玩家能力、怪物生命／力量和战斗合法动作。47 个场景对应 94 个战斗检查点，结论为 `coverage_gap`。遗物原始计数、剩余私有字段、旧样本里的强制奖励操作、自然整局与无 Mod 参照不在这次合同内。旧 47 条原始差异保持原状，不计为规则通过。

[事件原版输入](tests/fixtures/event-entry-original.json.gz)、[40 条配对报告](../../runs/parity-20260928/round20-event-entry-combined-v1/comparison/report.json)、[存档原版输入](tests/fixtures/save-entry-original.json.gz)、[7 条加载报告](../../runs/parity-20260928/round22-save-entry-v1/comparison-v2/report.json)、[配对边界记录](../../runs/parity-repair-20260928-preserved-insect/phase-pairing.json)。

加载报告的首版保留了一个检查工具错误：缺少 `FuzzyLouseDefensive` 到 `GREEN_LOUSE` 的 ID 映射。补齐原版与 native 的名称映射后，重放同一份捕获数据得到 7 个 `coverage_gap`；未重新捕获或改写原版状态。[首版报告](../../runs/parity-20260928/round22-save-entry-v1/comparison/report.json)保留为观察器错误证据。

本轮在这组检查旁发现并修复了 [昆虫标本抬高涅奥已降低生命的问题](REPAIR-20260928-PRESERVED-INSECT.md)。Pantograph 与 Slavers Collar 是否应在心灵绽放的 Boss 战触发，经原版源码核对按敌人 Boss 类型判定，现有 native 条件符合这条规则。哨卫消耗时的能量动作在两边当前源码中均入队首，[源码核对](../../runs/parity-repair-20260928-preserved-insect/source-audit.json)保留排除依据。
