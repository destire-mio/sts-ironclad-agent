# 铁甲战士 A20 心脏对齐（进行中）

验收范围：铁甲战士 A20，三把钥匙、第三幕双 Boss、第四幕矛盾与心脏；排除棱彩碎片。当前状态为 **INCOMPLETE**，不能用本目录的测试成绩证明训练环境与原版全内容一致。

`ironclad_a20.patch` 接在既有两份补丁之后。它修复战斗动作、状态导入、奖励与事件流转、牌组与遗物状态、随机数计数及心脏终局。`manifest.json` 记录固定上游提交与每个修改文件的摘要。Steam 的 Python 桥接代码与 Java 状态导出代码需要配套使用；旧导出缺少的怪物内部状态会影响恢复结果。

## 应用和测试

在上游提交 `7476a81954020087da31d41d16fddf475746ec2d` 上按下列顺序应用规则补丁：

```sh
git apply /path/to/sts-rl-agent/sim_patch/sim_rl_hooks.patch
git apply /path/to/sts-rl-agent/sim_patch/combat_rules.patch
git apply /path/to/sts-rl-agent/sim_patch/ironclad_a20.patch
git apply /path/to/sts-rl-agent/sim_patch/action_queue.patch
git apply /path/to/sts-rl-agent/sim_patch/parity_followup.patch
git apply /path/to/sts-rl-agent/sim_patch/e62_rules.patch
git apply /path/to/sts-rl-agent/sim_patch/e75_rules.patch
git apply /path/to/sts-rl-agent/sim_patch/e78_preview.patch
git apply /path/to/sts-rl-agent/sim_patch/e81_sever_soul.patch
```

独立的 CMake 入口构建 C++ 回归、Python 模块和整局流程驱动。需要 C++17、CMake、Python 开发环境、pybind11 与 nlohmann/json 头文件。

`parity_followup.patch` 对应 E64，修复 E63 的自动出牌死灵之书、零伤害荆棘、遗物获得顺序和 999 格挡上限。它改变战斗状态布局，核心、搜索和绑定须从源码一起编译；历史实验的冻结模块与对象不得混用。[增量清单](parity-followup-manifest.json) 记录六个源文件的前后摘要。39 条原版连续动作对照和五组原生回归包含在本目录测试中；消耗动画的费用时序差异保留在 E62 待办，不属于本轮通过范围。

```sh
cmake -S /path/to/sts-rl-agent/sim_patch/alignment -B build-alignment \
  -DSIM_ROOT=/path/to/sts_lightspeed \
  -DJSON_INCLUDE=/path/to/json/single_include \
  -DPython_EXECUTABLE=/path/to/python \
  -Dpybind11_DIR=/path/to/pybind11/share/cmake/pybind11
cmake --build build-alignment -j 4
ctest --test-dir build-alignment --output-on-failure
```

使用新模块时设置 `STS_LIGHTSPEED_BUILD=/absolute/path/to/build-alignment`。`agent/armG_train.py` 默认使用 A20，局面观察为 6820 维，候选描述为 805 维；旧的 412 + 368 输入权重不能加载到新模型。本轮没有进行 RL 训练或重测历史胜率。

## 原版对照工具

`tests/compare_cards.py` 比较一个动作；`tests/compare_sequences.py` 比较连续动作，可以通过 `ALIGNMENT_STRICT=1` 增加能力与意图检查，通过 `ALIGNMENT_REIMPORT=1` 检查每步恢复原版状态后的行为。输入是原版测试实例采集的 JSON，构建目录通过 `ALIGNMENT_BUILD` 指定。

`tests/replay_run.py` 从原版开局操作记录建立一个 `GameContext`，沿用模拟器的后续状态，比较牌组、生命、金币、药水、遗物列表、钥匙、战斗状态、奖励与随机数。它包含原版对话、确认按钮与模拟器动作的映射；映射错误作为错误报告。原版动画尚未完成的记录不能当作稳定状态。

原版采集依赖使用者的合法游戏安装及隔离运行适配器；游戏 JAR 不随本项目分发。本地采集程序和原始记录保存在工作区 `ironclad-alignment/oracle/`。这些适配器尚未做跨机器移植。

`full_chain SEED controlled` 使用 2000 生命与五张灼热攻击 +30 检查到心脏的流程；`natural` 使用初始牌组和既有策略。人工强牌结果与自然结果分开记录，死亡、异常、截断和缺钥匙终局不能合并成“胜负”。

## 本轮本地结果

9 月 12 日基线中，干净上游应用三份补丁后，114 项回归通过；开启 AddressSanitizer 与 UndefinedBehaviorSanitizer 后，相同 114 项（含最新 467 条原版夹具、27 条事件差分用例及 59 条本次复审对照记录）通过。`tests/fixtures/original-events-01.json` 记录 18 个此前无事件夹具的事件的原版对照；原版无决策引导屏被折叠为一次动作，决策集合与结果一致。其中 `tests/review18.cpp` 对应 9 月 12 日 review 的 18 项差异，相同测试在修改前呈现目标失败；修复包含商店补货与删牌、遗物获取／耗尽／献祭、事件奖励和地图飞靴。星系仪验证五组选牌及随机数续接，蜥蜴尾巴验证消耗状态在快照恢复后保持。`full_agent_simulation_total` 覆盖默认构造的 `ScumSearchAgent2`，确认 `simulationCountTotal` 初始为 0 且直接调用 `playoutBattle` 会确定性累加。

本轮原版隔离实例补充 23 个事件／遗物方法场景，结果字段对照不代表完整分支覆盖。原版两条人工强牌轨迹（数字种子 120、121）通过从开局到第 57 层心脏结算的连续回放。64 类遭遇的指定前五回合、13 个 Boss 阶段场景和 63 件遗物的指定战斗场景有原版对照证据。完整本地记录在工作区 `ironclad-alignment/对齐报告.md`，不随游戏 JAR 分发。

这些结果不等于全内容通过。清单把全部 50 个事件、149 件遗物都记为“部分覆盖”（有部分证据，不代表规则通过），分支和组合存在缺口。自然牌组心脏通关、真实存档往返及训练目标是验收门槛。

秘密传送门的事件资格依赖游戏时间。新局默认低于 800 秒；调用方应在房间选择前调用 `GameContext.set_play_time(seconds)` 提供外部游戏计时，回放会记录这种输入。不能拿本机模拟速度充当玩家的游戏时间。

## 证据边界

- 敌人前五回合、Boss 阶段切换和卡牌单动作对照只能支持对应场景。它们不覆盖所有敌人组合、能力叠加和遗物顺序。
- 《发现》及同类选牌药水会在原版的动画更新中消耗随机数。固定 30、60、120 FPS 场景有对照；帧间隔变化时，精确同种子回放还需要动画时间轨迹。工具箱使用另一种选牌动作。
- 自然轨迹从涅奥到第一幕死亡的回放有通过记录；自然开局到心脏的原版完整对照尚未通过。
- 事件分支、遗物组合、跨房间计数、保存与恢复仍有覆盖缺口。缺口保留为待验证，不能依据没有报警来宣布全部对齐。
- 本次改变了模拟规则、观察和动作空间，既有权重与评估结果没有迁移保证。训练恢复条件是对齐验收完成，并用心脏结果替换层数奖励。

## 开局与战斗入口复审修复

`tests/neow_entry_review.cpp` 与两份 `original-neow-entry-review.json`、`original-review-neow-extra.json` 夹具覆盖涅奥奖励和代价、诱变剂与人工的顺序、心灵绽放的 Pantograph 回血、红头骨回血跨半血线，以及添水下知晓头骨的随机数续接。本轮修复原复审 6 类差异和扩展检查 3 类差异。

59 条对照记录包含 36 条涅奥、5 条战斗入口、18 条组合及事件记录；数量存在场景重叠，不代表 59 个独立机制。涅奥扩展扫描包含 30 组奖励与代价生成状态，后续选牌分支的完整覆盖仍属于验收缺口。

## 9 月 13 日候选、属性与连续动作复查

交付补丁包含 45 个模拟器文件；从固定上游应用、构建后的 140 项 CTest 通过。新增的 `original-repair-outside.json` 包含 402 条选牌、转换、遗物、商店与药水槽位对照，`original-card-metadata.json` 包含 132 张牌的 264 个基础／升级属性状态。五组 `original-repair-*.json.gz` 连续记录共 381 条，其中 373 条执行通过，8 条状态牌由两端拒绝；`original-prior-sequences.json.gz` 包含 198 条历史有效记录。夹具来源摘要在 `tests/fixtures/repair-provenance.json`。

修复包括空鸟笼与增幅者的瓶装候选、牧师的空候选扣款、商店删牌与营火取消、颂钵及局外药水候选、添水的商店／奖励动作、送货员按牌型补货、混沌药水填槽顺序、磁力和乱战的回合效果、异鸟落地、贪婪之手受击触发、生成牌满手费用、反伤击杀后停止多段攻击，以及临时降费和以血还血的升级费用。

自然路线对照补充修复了强化精英少 1 点力量、扎人之书开战多加 1 次连刺的问题；蠕动肿块“枯萎”的预测伤害从 0 修正为 A20 的 12。连续对照增加招式基础伤害与攻击次数检查。靶向药水的丢弃动作说明不再把丢弃标记当成敌人下标，修复前可触发崩溃。

原版构造牌与升级牌的属性对照修复了狂怒（Rage）／绊倒的基础费用、地狱之刃的升级费用、残暴／自燃的颜色。转换池排除原牌后的索引、无色源池顺序和 Astrolabe 的无色升级均有原版场景。卡牌颜色变化会改变旧 NNInterface 的编码位置，旧权重需要重验。

`compare_sequences.py ... --check` 在规则、合法性、导入或原版夹具错误时返回失败；状态牌被原版拒绝且模拟器也拒绝，才计为合法性通过。普通的退出码不能替代结果字段检查。CTest 会为每组夹具保存独立报告到构建目录的 `original-comparisons/`。

送货员的原版颜色牌补货还使用全局 MathUtils 随机流；本轮对照固定该外部状态。真实界面动画的随机消耗和时间输入不由一个游戏种子决定。自然初始牌组到心脏、事件／遗物全分支和保存恢复覆盖仍未完成，项目状态保持 INCOMPLETE。

macOS 使用带 ASan／UBSan 的 Python 模块时，Homebrew 的普通启动器可能导致 ASan 加载过晚。C++ 与局外 CTest 可用 `ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1` 执行；六组连续对照可用同一 Python 版本运行 `python tests/sanitized_sequences.py /absolute/path/to/build-sanitized`。启动器选择 Framework Python 并为子进程预加载 ASan，只改变检测器启动方式。报告保存在构建目录，未定义行为会使该次比较失败。

`original-natural-trace.json.gz` 保存自然种子 129 的 1002 条原版命令与动作轨迹，从起始牌组到第 51 层败北结算连续吻合，包含三把钥匙和第三幕双 Boss。`replay_trace.py` 比较时不导入中途状态。此轨迹不能充当自然心脏通关。无颂钵时关闭选牌不会删除原版奖励，策略通过离开奖励页放弃剩余卡牌。简单策略领取瓶装遗物后等待子界面选择，避免把下一张奖励的动作误发到瓶装界面。

## 9 月 14 日 A20 训练接口

第三份补丁增加 `pause_on_all_out_of_combat_decisions`。开启后，奖励、地图、篝火、事件、商店、Boss 遗物、宝箱和选牌子界面的合法动作全部交给外部策略。Python 候选编码器为每个合法动作生成一个 805 维描述和一个执行器；动作数量不一致或画面不受支持时抛出错误。本轮范围排除棱彩碎片，模拟器会用完整商店遗物池完成原版洗牌，再移除棱彩碎片；策略不会遇到一件效果关闭的空遗物，随机数消耗和其余遗物次序不变。

6820 维局面观察覆盖三把钥匙、药水槽、遗物计数、卡牌 ID／升级次数／`misc`／瓶装身份、完整可见地图和事件可见状态。事件候选补充涅奥祝福与代价、坠落卡牌、恩洛斯遗物、再次相遇物品和留给自己的纸条；记忆翻牌不会泄露未翻牌面。三把钥匙由策略选择后进入第四幕的流程、棱彩碎片排除、所有局外画面的暂停以及 Python 候选合同进入 CTest。

当前并行训练器仍按最终层数计算回报。它可以用于短程冒烟和采样管线检查，不能作为 A20 心脏策略的正式目标；正式实验需要固定搜索预算，用候选动作后的完整续局心脏结果训练和评估。

新增 `agent/heart_train.py` 实验入口使用独立的心脏目标合同。`resolve_battle_recorded` 复用原战斗执行器并返回实际动作，`SearchAction.from_bits` 用于合法动作前缀重放；自然节点通过种子与全部动作恢复，不浅拷贝局外上下文。新版回归为 141 项，包含 `heart_training_contract` 中 8 项标签、重放、隔离和参数更新检查。该实验不解除本清单的原版对齐缺口。

## 9 月 14 日扩大采样后的越界修复

`CardInstance::canUse` 在觉醒者等待复活、场上没有可攻击目标时使用了 -1 敌人下标。候选续局在 ASan／UBSan 下复现数组越界；修复在读取敌人前检查下标范围。`untargetable_card_bounds` 检查无目标时拒绝单体攻击、允许无目标防御、复活后恢复攻击合法性。加入 `heart_expansion_contract` 后，普通构建与干净补丁构建各通过 143 项 CTest。两条原故障路径合计 249 个完整候选续局通过内存检查。

使用旧模块的第二轮实验已停止并作废标签；修复后的轮次重新生成自然前缀和心脏结局，保持原始种子分区。修复不构成自然心脏原版连续重放的验收结论。


## 2026-09-19：E75 原版复验与 E76 修复

E75 覆盖预先固定的全部 53 条 E67 开发胜局：21 条自然开局至心脏的状态及 RNG 匹配，26 条首次差异，6 条回放映射错误。它不提供总体原版胜率。[E75 摘要](e75-development-parity-report.json)保留全部分类。

`e75_rules.patch` 修复 11 类差异，接在 `e62_rules.patch` 后；[增量清单](e75-rules-manifest.json)记录 8 个文件摘要。15 组针对性测试在旧源码上为 13 个目标失败、2 个对照通过，修复后通过 15 组，完整本地 CTest 通过 176 项。26 个自然首次差异中修复后匹配 24 个。棱彩碎片保留原版商店池与报价位置，购买候选被排除。当前剩余为诅咒变牌预览 RNG、六条回放映射和修复后的整局复验。E73 保持暂停。[E76 摘要](e76-rule-repair-report.json)给出证据范围；以上历史段落保留当时状态，不能用其测试数量认定当前全面对齐。


E78 adds persistent transform-preview timing (`e78_preview.patch`, applied after `e75_rules.patch`). The default natural input is one confirmation update at float32 1/60 second; explicit positive frame count/delta and the carried timer enter replay identity. Rebuild the core and bindings. Five original natural timing controls, 26 earlier first-divergence boundaries, and three deeper UI boundaries match. Full CTest: 183; independently applied portable focused checks: 8. Controlled OutsideProbe fixtures bypass the original animation and retain zero preview updates for that separate test boundary. Current results and remaining full-run requirements are recorded in the training status.

The supplied `verify_heart_winners.py` is the original-game replay driver, not a self-contained original-game installation: it requires the private licensed-game oracle runner and a frozen local cohort. `e78-preview-observer.patch` adds read-only timer observation to that local oracle. No game JARs, licensed game source, checkpoints, or raw private traces are included.


E81 (`e81_sever_soul.patch`, after `e78_preview.patch`) fixes Sever Soul exhaust scheduling: Feel No Pain callbacks resolve before the Heart's Beat of Death, while reverse hand exhaust order and Dead Branch RNG are preserved. Four before-repair target failures become passes; three controls remain passing. Full CTest:190; separately applied portable focused checks:7. The natural divergence boundary and a full historical-action original Heart route (1,083 commands,36HP) match. Fresh replanning of that seed loses at Awakened One, so E79 outcomes are not transferred; E82 regenerates the cohort. This is a confirmed rule repair, not an improved-policy or exhaustive-parity claim. See [repair evidence](e81-sever-soul-report.json).
