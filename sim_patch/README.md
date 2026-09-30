# 固定模拟器版本的战士战斗规则修复

A20 至心脏的扩展对齐工作见 [alignment/README.md](alignment/README.md)。第三份补丁 `ironclad_a20.patch` 包含训练观察、统一局外决策入口与配套状态导出修改；整体原版对齐状态仍为 INCOMPLETE。下文保留既有 `combat_rules.patch` 的范围与历史结果边界。

对应 [issue #1](https://github.com/Jialeiv/sts-rl-agent/issues/1)。本补丁覆盖战士能够触发的药水、铁斩波和耗尽牌堆后的战斗结算，不增加角色支持。

## 应用补丁

在 `sts_lightspeed` 的 `7476a81954020087da31d41d16fddf475746ec2d` 提交上执行：

```bash
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

第一份补丁提供基础接口和暂停功能，第二份修改战斗规则，第三份增加 A20 至心脏的规则、状态与训练接口，第四份修复动作队列容量及战斗结束后的队尾。第四份改变 `BattleContext` 的内存布局，必须重编所有游戏核心、搜索和 Python 绑定对象，不能与旧静态库或绑定对象混合链接。

第五份 `parity_followup.patch` 修复 E63 的四类差异：自动出牌的死灵之书触发和复制 X 费牌的能量支付、零伤害攻击的荆棘、按遗物获得顺序执行出牌回调、玩家 999 格挡上限。自然战斗初始化与快照导入共享遗物顺序记录，MCTS 分支按值复制该记录。它改变 `Player`／`BattleContext` 布局，要求从源码重编核心、搜索和绑定；不能复用 E61 或旧实验的对象文件。

新回归入口为 `alignment/CMakeLists.txt` 中的 `parity_followup_*` 和 `repair_original_parity_followup`。后者包含 39 条保留的原版连续动作序列；修复前有 11 条不一致，修复后通过。E62 的其余问题及自然开局至心脏的原版验收列为待处理。完整记录见工作区的 `ironclad-alignment/evidence/parity-repair-e63-20260918-01/修复报告.md`；分发文件身份见 [parity-followup-manifest.json](alignment/parity-followup-manifest.json)。

## 改动与验证条件

- **血液药水**：普通效果回复最大血量的 20%，神圣树皮加成为 40%。回归覆盖普通效果、树皮、整数截断和血量上限。
- **铁斩波**：格挡修正计算一次，覆盖敏捷、负敏捷、升级和脆弱，检查攻击伤害没有改变。该项与上游 [gamerpuppy/sts_lightspeed#9](https://github.com/gamerpuppy/sts_lightspeed/pull/9) 的已有修复一致。
- **无牌状态**：删除提前判负的有限条件列表。战士使用恶魔之焰消耗剩余手牌后，可以使用火焰药水，或使用毒药水后结束回合获胜；没有后续伤害来源时，由敌人的实际攻击结算败北。
- **毒药水结算**：原 `PoisonLoseHpAction` 返回空动作，敌人回合开始时执行会抛出异常。补全有目标的毒伤动作，保留入队时的目标与毒伤量，绕过格挡，复用无格挡伤害与死亡处理，并减少一层毒。回归覆盖击杀先于敌人攻击、格挡、无实体、毒层数归零、人工制品及多敌人隔离。

测试从战士对邪教徒的状态构造合成场景，通过模拟器出牌、药水和结束回合入口执行。原版预期根据本地原版 Java 规则核对；这些用例不构成完整的原版双引擎回放验证。

## 原生回归命令

不依赖 Python 绑定、PyTorch 或模型权重。需要 C++17 编译器、CMake，以及模拟器的 `json` 子模块。运行目录可以是模拟器根目录：

```bash
cmake -S /path/to/sts-rl-agent/sim_patch/tests -B build-combat-tests \
  -DSTS_SIM_ROOT="$PWD" -DCMAKE_BUILD_TYPE=Debug
cmake --build build-combat-tests -j 4
ctest --test-dir build-combat-tests --output-on-failure
```

若使用已有的 nlohmann/json 头文件目录，可以在配置时设置 `-DSTS_JSON_INCLUDE=/path/to/json/single_include`。

测试使用显式检查与非零退出码，发布构建关闭 `assert` 不会关闭测试判定。每个测试由独立进程执行，超时为 10 秒。要复现修复前失败，在只应用 `sim_rl_hooks.patch` 的同一版本上运行同一套测试。

## 结果边界

移除无牌提前判负后，一些没有获胜路线的搜索分支可能需要模拟更多回合。上游现有的 500 回合保护及其他搜索限制不在本次修改范围；本补丁不提供搜索耗时或全局最优性的保证。

上游将敌人毒层数保存在有符号 8 位整数中；累加到 150 层会读出 -106。这一高层数存储问题不在本补丁范围，毒药水回归覆盖的层数没有跨过该边界。

项目现有评估表来自该规则补丁之前，未用修复后的模拟器重新评估；历史数字保留其原有版本含义。

## MCTS 推演配置

`search_rollout.patch` 保存 E18 开发对照和 E19 未见种子评估使用的搜索版本。它在上述三份补丁之后应用，修改搜索器，不修改游戏结算或候选合法性：

- 全负推演分数也能保存最佳序列，相等回报避免除零。
- UCB 使用已访问均值、回报区间归一化，以及未访问边优先探索。
- 随机推演中存在合法出牌时，结束回合相对权重为 0.1。搜索树仍保留结束回合，推演中也保留非零概率。

在模拟器源码副本中复现该候选：

```bash
git apply --check /path/to/sts-rl-agent/sim_patch/search_rollout.patch
git apply /path/to/sts-rl-agent/sim_patch/search_rollout.patch
```

应用前搜索源文件 SHA-256 为 `1b223ccb8da09f57e175e623b8b7387b7b3069fa57b7fe0b8bbf3f5210efeb41`，应用后为 `fa3f0b77507571c4a81fa6f23cbb1ef2c519937f3b1d671c2d5231a45c618a71`；输出源码与 E18 已测构建逐字节相同。需要编译并通过新进程加载，现有冻结引擎不应覆盖。

本机的隔离构建入口是 `agent/heart_search_build.py`。它读取 `ironclad-alignment/build/` 中归档的游戏规则库和两份 Python 绑定对象，在新目录分别编译原搜索、数值边界修正、归一化和推演变体，记录编译命令、源码／对象哈希与 `search_numerics.cpp` 结果。该流程固定 macOS arm64／Python 3.12 的对象格式；跨平台复现需要从对应平台源码构建。

数值回归的两项原缺陷为 `negative_playout`、`equal_returns`；`return_translation` 和 `unvisited_edge` 是归一化版本新增的评分约定。不要把四项检查都解释为原版游戏规则错误。完整对照与未见种子验收见[实验账本第 28 节](../../铁甲战士项目路线与RL实验.md#combat-search-e19)。

## 出牌顺序推演

`search_order.patch` 是 E22—E25 使用的增量搜索补丁，在前三份对齐补丁和 `search_rollout.patch` 之后应用。随机推演选中牌动作后，以 50% 概率从现有 `getPlayOrdering` 优先级最高的合法牌／目标中均匀选择；其余情况保留原选择。出牌、药水、结束回合三类动作的抽样概率和搜索树合法分支保留，游戏规则对象不变。

```bash
git apply --check /path/to/sts-rl-agent/sim_patch/search_order.patch
git apply /path/to/sts-rl-agent/sim_patch/search_order.patch
```

应用前搜索源文件 SHA-256 为 `fa3f0b77507571c4a81fa6f23cbb1ef2c519937f3b1d671c2d5231a45c618a71`，应用后为 `64387b31618d508e4b58d954f9ddcc9e3175fae44ffb20ca493efd6082da6529`。隔离副本上的补丁检查与应用通过，输出与实际编译的候选源码逐字节一致。构建入口 `agent/heart_order_rollout.py build` 复用前版归档规则及绑定对象，输出到新目录；平台限制同上，不覆盖默认原生模块。

E25 在同一批 1,024 个全新种子上，前版 20 胜、候选 33 胜，新增 23、损失 10，配对 p=0.035082；每次 8,000／Boss ×3，整局搜索量增加 7.28%。53 次胜局规划重跑和完整路线核验通过。候选通过采用门槛，10% 目标未达到；它不构成局外网络学习或原版 Java 对齐证据。[可读结果](../runs/heart-order-acceptance-20260917-01/验收结果.md)、[冻结运行时决定](../runs/heart-order-acceptance-20260917-01/decision.json)、[补丁应用核验](../runs/heart-order-acceptance-20260917-01/portable-patch-verification.json)、[实验账本第 34 节](../../铁甲战士项目路线与RL实验.md#combat-search-e25)。

## 绑定编译产物刷新

E32 发现继承的核心对象按 `-O2` 编译，绑定对象的旧生成选项却没有优化等级。当前源 CMake 包含绑定 `-O2`，但历史归档对象并未刷新。检查源码选项不能替代检查生成命令和已加载模块。

`agent/heart_binding_optimization.py build --root <新目录>` 在本机快照相同绑定源码、头文件与对象，分别构建 O0 控制和 O2 候选；复用 E25 的规则库与搜索对象，保留断言和链接参数。完整命令与哈希写入 `build-report.json`。这个入口依赖本机归档的 macOS arm64／Python 3.12 对象，不是跨平台构建器，也不覆盖默认模块。没有新增游戏或搜索补丁。

O0 重建模块与 E25 的 `931cc829…` 逐字节相同。O2 模块 SHA-256 为 `62bcc5a7673b5e15e5b8f2362f800740ba2a2560361f9c075cc5ba61fc406385`；两种重建各通过 256 单战与 64 整局的行动、搜索量、终态和 RNG 对照。原搜索数值检查属于复用对象的历史结果，不算作新绑定测试。

固定 16 状态重复 8 轮的平衡配对测试中，搜索耗时降幅中位数 7.05%，按轮 bootstrap 95% 区间 6.90%—7.19%，通过 5% 预设门槛。采用 O2 运行时进行后续实验，网络和搜索预算保持；没有把 E26／E29／E30／E31 的拒绝候选合入。这份计时结果不代表全训练吞吐率或新的未见种子胜率。

复用入口为 [E32 决定](../runs/heart-binding-validation-20260917-01/decision.json) 的 `selected_runtime`；新实验冻结源码／模块／权重并核对 SHA，保留旧标签的引擎身份。[可读结果](../runs/heart-binding-validation-20260917-01/优化结果.md)、[构建记录](../runs/heart-binding-build-20260917-01/build-report.json)、[结束核验](../runs/heart-binding-validation-20260917-01/completion-verification.json)、[实验账本第 41 节](../../铁甲战士项目路线与RL实验.md#runtime-speed-e32)。

## 动作队列修复（E50）

E49 的自然根 `166835586` 在 A20 第二幕第 29 层扎人之书的搜索中触发 `ActionQueue<50>::pushBack` 容量断言。原版 `GameActionManager` 使用可增长列表，50 不是游戏规则限制。`action_queue.patch` 为常规队列保留 50 个内联位置，满时扩容，按值复制搜索分支的队列。执行中的回调与队列存储分离，回调追加动作导致扩容时不会失效。

另一处错误是战斗胜利后压缩保留动作时，没有移动队尾；后续追加可能跳过或重复执行效果。修复把稳定过滤放回队列自身并更新队尾。原版 Java 类的合成动作测试确认可容纳 512 个动作，清理后的追加顺序为 `[11,4,7,8,10]`；这个测试验证队列语义，不证明所有动作的清理标记或原版整局一致。

修复前的规则源码重建与 E32、E45 两份原生模块逐字节相同；修复后重编 29 个游戏核心、2 个搜索、2 个绑定对象。8 项队列用例在 ASAN/UBSAN 下通过，旧实现重现容量断言和队尾顺序错误；143 项现有原生、训练接口与原版存档夹具检查通过。2,046 条旧有效轨迹中 2,016 条状态/RNG 一致，30 条在胜利结算后变化；只修改旧队尾的一份控制引擎逐条复现这 30 个变化后的完整状态，因此这些变化归因于队尾修正。

43 对已检查种子的整局重跑与 22 次胜局复跑通过，含两个故障种子。这个面板含历史胜局，不能用来估计未见种子胜率。超时案例在新引擎下耗时约 123.55 秒走到觉醒者死亡；下一轮两组的整局/进程保护在抽种子前固定为 300/360 秒，每次搜索仍为 8,000、Boss ×3。旧 E49 故障记录保留。

源码补丁 SHA-256：`138bcc0a86d087bb8a531840c49ce60de98d5941e9a445054e7c901cc1043350`。修复后的均值引擎为 `8aa40d11b33764a339749e82c39d635b74794bad6a76fc9ad2decc1010ebc25e`，最大值引擎为 `f01adb43ee141b7f9e84c328d7a275e1a38f0b31690260e695c27d2cba25d1be`。源码修改应用到本地 `ironclad-alignment/simulator`，旧冻结模块没有覆盖。[修复核验](../runs/heart-action-queue-validation-20260918-01/completion-verification.json)、[构建记录](../runs/heart-action-queue-build-20260918-01/fixed-build-report.json)、[补丁核验](../runs/heart-action-queue-build-20260918-01/portable-patch-verification.json)。

可移植队列用例入口为 `tests/action_queue.cpp`，沿上述 CMake 配置增加 `-DSTS_QUEUE_SANITIZERS=ON`，然后执行：

```bash
cmake --build build-combat-tests --target action_queue -j 2
ctest --test-dir build-combat-tests -R '^queue_' --output-on-failure
```

`tests/QueueOracle.java` 使用本机合法原版 JAR 中的 `GameActionManager`，以合成 `DAMAGE/DRAW` 动作检查队列，不包含或分发原版字节码。跨平台构建应从源码编译所有对象；旧章节的预编译对象复用入口属于其历史布局。

## 最大值搜索与败局加分上限（E54）

`search_bounded_loss.patch` 在 `search_rollout.patch` 和 `search_order.patch` 后应用，运行时要求 E50 的 `action_queue.patch` 及其完整 ABI 重编。它把节点备份与利用项从平均回报改为最佳已知回报，并将败局中的抽牌／回合加分之和限制为 20。胜利公式、合法树、推演抽样概率、探索系数及局外网络沿用原配置。上限下保留数学公式，但浮点加法重新分组，不承诺逐位相同。

同一批 1,024 个新根，对照 34 胜、候选 68 胜；新增 40、损失 6，配对 p=3.1028e-7。2,048 个自然终局、102 次胜局重规划与路线／网络核验通过，执行故障 0，整局搜索量增加 24.13%。通过采用门槛，样本成功率 6.6406%，10% 目标未达到。收益属于这组战斗搜索修改，不能单独归因于上限，也不代表局外网络学习或原版整局对齐。

```bash
git apply --check /path/to/sts-rl-agent/sim_patch/search_bounded_loss.patch
git apply /path/to/sts-rl-agent/sim_patch/search_bounded_loss.patch
```

增量输入源码 SHA-256 为 `64387b31618d508e4b58d954f9ddcc9e3175fae44ffb20ca493efd6082da6529`，输出为 `c20146a5a6e549c402eca200be4e2567e5f7e7da88fb49d763d22ac42a06878b`。三份搜索补丁的完整应用链与编译输入匹配，本地模拟器搜索源码采用该输出。[E54 冻结运行时](../runs/heart-bounded-loss-confirmation-20260918-01/selected-runtime.json)保留为历史入口；E60 在此搜索器上加入下述控制器保护和局外遗物模型，没有覆盖历史原生模块。

在上述 CMake 配置时添加 `-DSTS_BOUNDED_LOSS_TESTS=ON`，可以从应用补丁的源码运行六项搜索评分合同：

```bash
cmake --build build-combat-tests --target search_terminal_loss -j 2
ctest --test-dir build-combat-tests -R '^bounded_loss_' --output-on-failure
```

六项检查覆盖常规败局数学公式、极端加分平台、敌人受伤的进展、胜利公式、合成高抽牌败局与胜局的顺序、未终局的评分边界。这些是搜索评分合同，不是原版游戏规则修复。CMake 入口从匹配的源码编译并通过六项检查；旧源对照在极端平台与合成胜负顺序两项失败。

证据：[验收结果](../runs/heart-bounded-loss-confirmation-20260918-01/验收结果.md)、[整局核验](../runs/heart-bounded-loss-confirmation-20260918-01/completion-verification.json)、[源码应用链](../runs/heart-bounded-loss-confirmation-20260918-01/source-chain-verification.json)、[本地源码接入](../runs/heart-bounded-loss-confirmation-20260918-01/live-source-adoption.json)、[CMake 检查](../runs/heart-bounded-loss-build-20260918-01/portable-check/result.json)。


## 重复搜索保护（E58 训练运行时）

`search_replanning_limit.patch` 针对 `ScumSearchAgent2.cpp`，在 E54 配置上将单战重新搜索次数限制为 256。达到上限后执行有效的已知胜利方案，或本次搜索从当前局面找到的有限终局方案；找不到终局时保留执行错误，不能把保护触发直接记为死亡。它不改变合法动作、游戏规则、每次 8,000／Boss ×3 的预算或局外模型。

该方案用于 E59 的训练运行时。41 个自然开局控制的动作、搜索数、终态与 E54 相同，故障根 `648297286` 在约 30.34 秒到达死亡终局；3,072 条自然轨迹的动作／NN／终态／RNG 审计与 247 次胜局重新规划通过。3,071 条轨迹来自满足调用次数边界的旧轨迹迁移，原生成引擎和源文件哈希保留；另外 1 条是新生成。原 E55 故障记录没有改写。这些结果不提供新的未见种子通关率。

相邻实验 E57 的“发现败局就执行方案”使开发成绩从 7/38 降为 4/38，已拒绝，不包含在此补丁。此处保护只在第 256 次搜索后触发。

E60 两组共享该保护，原局外网络与学习首幕 Boss 遗物的策略在同一批新根上为 83→112/1,024；2,048 个终局、195 次胜局重规划及路线／NN／RNG 核验通过，执行故障 0。该对照支持遗物策略的收益，不能单独归因为控制器保护。当前推理入口为 [E60 冻结运行时](../runs/heart-first-boss-confirmation-20260918-01/selected-runtime.json)，见[完整验收](../runs/heart-first-boss-confirmation-20260918-01/验收结果.md)。

本地 `ScumSearchAgent2.cpp` 接入该补丁，输出 SHA 为 `e088dbb0ac029a493eca4607f2049ae71c7cd86de140146620bf3573f45d19d6`，与受测编译输入相同。[接入证据](../runs/heart-first-boss-confirmation-20260918-01/live-source-adoption.json)记录前后哈希；推理从所选运行时加载配对的模型和原生模块。

补丁在隔离源码上检查和应用，输出与候选编译输入相同。[构建与修改说明](../runs/heart-bounded-replanning-build-20260918-01/build-report.json)、[补丁核验](../runs/heart-bounded-replanning-build-20260918-01/portable-patch-verification.json)、[训练运行时核验](../runs/heart-bounded-replanning-validation-20260918-01/completion-verification.json)。

## E62 规则与随机数修复

`e62_rules.patch` 接在 `parity_followup.patch` 后，修复 20 类 E62 游戏行为和 RNG 差异。它改变 GameContext 状态和 Deck 获牌接口，要求重编核心、搜索、绑定。配套生产桥接修复无目标药水误当丢弃的问题。12 条原版动作边界、8 条本地自然前缀、10 组新增原生回归和整套 161 项 CTest 通过；独立分发构建的 12 个针对性入口通过。历史原版耗尽动画费用诊断保留，完整自然开局至心脏的原版一致性尚未通过。详见 [训练状态](../docs/ironclad-training-status.md) 与 [分发清单](alignment/e62-rules-manifest.json)。

## E68 原版自然路线与目标映射

E66 引擎下四条预选开发胜局通过原版自然开局至 A20 心脏的相同行动重放，共 4,080 条原版操作；逐步比较状态与 RNG。`steam/steam_mcts.py` 修复了史莱姆分裂后消失母体干扰目标编号的问题，保留死亡子体和后续分裂需要的槽位。六个映射用例旧版失败五个、修复后全部通过，161 项 CTest 通过。

核验器等待原版消耗动画的费用重置回调完成，未修改原版费用或 RNG。四条路线与稳定动画边界不构成全部内容对齐，也不是模型在原版上的总体胜率。结果及历史失败口径见 [E68 报告](alignment/e68-natural-parity-report.json)。


E78 adds persistent transform-preview timing (`e78_preview.patch`, applied after `e75_rules.patch`). The default natural input is one confirmation update at float32 1/60 second; explicit positive frame count/delta and the carried timer enter replay identity. Rebuild the core and bindings. Five original natural timing controls, 26 earlier first-divergence boundaries, and three deeper UI boundaries match. Full CTest: 183; independently applied portable focused checks: 8. Controlled OutsideProbe fixtures bypass the original animation and retain zero preview updates for that separate test boundary. Current results and remaining full-run requirements are recorded in the training status.

The supplied `verify_heart_winners.py` is the original-game replay driver, not a self-contained original-game installation: it requires the private licensed-game oracle runner and a frozen local cohort. `e78-preview-observer.patch` adds read-only timer observation to that local oracle. No game JARs, licensed game source, checkpoints, or raw private traces are included.


E81 (`e81_sever_soul.patch`, after `e78_preview.patch`) fixes Sever Soul exhaust scheduling: Feel No Pain callbacks resolve before the Heart's Beat of Death, while reverse hand exhaust order and Dead Branch RNG are preserved. Four before-repair target failures become passes; three controls remain passing. Full CTest:190; separately applied portable focused checks:7. The natural divergence boundary and a full historical-action original Heart route (1,083 commands,36HP) match. Fresh replanning of that seed loses at Awakened One, so E79 outcomes are not transferred; E82 regenerates the cohort. This is a confirmed rule repair, not an improved-policy or exhaustive-parity claim. See [repair evidence](alignment/e81-sever-soul-report.json).


`replay_recorded_winner.py` rechecks identical natural action/timing paths against immutable original responses using the pinned live comparator and additional run-only RNG checks during combat. It performs no new JVM run and never imports original state. Changed paths require new original execution. Eight known-route/negative cases and six input-integrity checks validate this boundary; source records and licensed oracle dependencies remain local. See [E83 evidence](alignment/e83-recorded-replay-report.json).


E85 (`e85_dropkick.patch`, after `e81_sever_soul.patch`) captures Dropkick damage at use so Akabeko Vigor is included before removal. The queued Vulnerable draw/energy condition remains unchanged. Five target failures and two controls become seven passes; full CTest198 and portable focused7 pass. All90 portable source inputs match after applying the separately required frozen search patches. The natural divergence and a fresh planned original Heart route(1,371 commands,37HP) match. A separate historical route exposes a deeper temporary discard-cost difference; training remains paused. See [E85 report](alignment/e85-dropkick-report.json). Never treat the targeted passing route as an unseen population win rate.


## Guardian defensive transition (E98)

Apply `e98_guardian_queue.patch` after `e86_discard_copy.patch`, then rebuild the core, search and bindings together. The repair queues the defensive state change before that action appends Mode Shift removal and 20 block. This allows queued follow-up damage to resolve before block and preserves pending-transition state in copied MCTS branches. No policy or search-budget change is included.

The old engine fails six of ten targeted C++ groups; all ten pass after repair, together with 214 local CTest cases. Seven controlled original card sequences and two selection boundaries match. The fixed natural E97 divergence seed also matches an original A20 Heart route of 1,115 commands at 49HP, with keys, both Act 3 bosses, Act 4 and added persistent-RNG checks. This is targeted repair evidence; affected historical training labels require regeneration, and exhaustive parity remains incomplete.

[Patch manifest](alignment/e98-guardian-queue-manifest.json), [result](alignment/e98-guardian-queue-report.json), [regressions](alignment/tests/e98_guardian_queue.cpp).


### E102: Spot Weakness and Writhing Mass attack intent

Apply `e102_spot_weakness.patch` after `e98_guardian_queue.patch`, then rebuild core/search/bindings together. `WRITHING_MASS_WITHER` has an attacking native intent and now triggers Spot Weakness; Exploder's UNKNOWN explosion remains a nonattack. The game-source change adds one move-table entry.

Three target groups fail on the old library and pass after repair; four controls pass under both. All221 CTest cases and seven portable focused cases pass. The same751-action natural prefix matches18 recorded native Spot Weakness boundaries, including the prior Strength2-versus5 divergence. The preselected seed192246470 replans to a Heart victory, repeats identically, passes207 outside-NN audits and matches1,090 original commands through Time Eater/Donu and Deca, Shield/Spear and Heart at15HP, including added persistent-RNG checks. This is a rule-repair control, not a new trained model or population win-rate claim. E99 stays stopped; affected sources/labels must be regenerated under a new registration.

[Patch manifest](alignment/e102-spot-weakness-manifest.json), [result](alignment/e102-spot-weakness-report.json), [regressions](alignment/tests/e102_spot_weakness.cpp).


### E106: Unceasing Top queued draw effects

Apply `e106_unceasing_top.patch` after `e102_spot_weakness.patch`, then rebuild core/search/bindings together. When Top's draw schedules shuffle/refill or on-draw actions, finish the action queue before returning player input. Preserve NoDraw, empty-pile and no-Top controls.

Ten focused C++ groups pass (six failed before repair); full CTest231 and portable10 pass. Nine original sequence controls and three recorded natural boundaries match. Two rejected Abacus fixture IDs remain documented; the actual native constant is TheAbacus. The preselected repaired natural route and its repeated plan pass196 outside-choice checks and1,069 original commands, with three keys, two Act3 bosses, Act4/Heart at49HP and persistent-RNG checks. This is scoped repair evidence, not an exhaustive-parity or win-rate claim.

[Patch manifest](alignment/e106-unceasing-top-manifest.json), [result](alignment/e106-unceasing-top-report.json), [regressions](alignment/tests/e106_unceasing_top.cpp).


### E110 and E111: generated-card capture and victory state

Apply `e110_dead_branch_capture.patch` after E106, then `e111_post_victory_exhaust.patch`; rebuild core, search and Python bindings together. E110 captures a Dead Branch card before queued after-use HP loss. E111 applies the native dead-monster guards to Dead Branch and Dark Embrace and resets five room RNG streams when Heart victory enters VictoryRoom.

E110's full original integration found the subsequent Sundial mismatch, so its scoped result does not admit source collection. E111 resolves it: 250 CTest cases, 19 portable cases, five new original controls and nine E110 controls pass. The preselected failure seed repeats a natural Heart win; 203 outside choices, 1,065 original commands and twelve terminal RNG streams match. This is repair evidence, not a population win-rate claim. Initial fixture-index and build-configuration mistakes are preserved in the reports.

[E110 manifest](alignment/e110-dead-branch-capture-manifest.json), [E110 scoped result](alignment/e110-dead-branch-capture-report.json), [E111 manifest](alignment/e111-post-victory-exhaust-manifest.json), [E111 completed result](alignment/e111-post-victory-exhaust-report.json).


### E116: independent Bomb powers

Apply `e116_bomb_instances.patch` after E111, then rebuild core, search and Python bindings together. Bombs retain separate countdowns and damage actions; queued reductions address branch-local instances. `Player.bombs` remains a derived three-total view, while `Player.bomb_instances` exposes every `(turns, damage)` pair. Missing or nonpositive imported countdowns reject the snapshot.

263 CTest cases and 31 clean portable cases pass, including public import/copy regressions. Four recorded original controls and one preselected full natural route pass with additive per-instance power checks and twelve terminal RNG streams. The failed initial patch-application attempt is preserved. This admits a newly registered source refresh, not old E112 labels, model improvement or exhaustive parity. Relative ordering among different power types remains outside the scoped repair.

[Manifest](alignment/e116-bomb-instance-manifest.json), [completed result](alignment/e116-bomb-instance-report.json).


### E121: player turn power order

Apply `e121_power_order.patch` after E116 and rebuild core, search and Python bindings together. Player state retains priority and stable acquisition order, including individual Bombs. Stacking keeps position; removal and reapplication update it. The existing start, post-draw and end-turn callback loops consume that order; snapshots, copies and `Player.power_order` preserve it.

279 local checks, 47 clean portable checks and four recorded E120 original sequences pass. The registered natural/original Heart integration passed, including all outside choices, phase-specific order and twelve terminal RNG streams. Register a new source under E121; old E117 outcomes do not become new-engine labels. Other hook phases remain outside this scoped repair.

[Manifest](alignment/e121-power-order-manifest.json), [preparation](../docs/experiments/e121-repair-preparation.json).

[Completed E121 result](alignment/e121-power-order-report.json). The preparation link above is its historical pending checkpoint.

### 疼痛与虚空的结算顺序

`pain_void_order.patch` 接在 `e121_power_order.patch` 后应用，性能优化版可应用同一补丁，然后重编核心、搜索与 Python 绑定。疼痛失血标为玩家自身造成，以触发撕裂；虚空的扣能量放入队尾，在执行分支中结算，并遵循战斗结束后的动作清理。

8 个原版场景回放的被比较字段吻合，284 个 CTest 入口通过，冻结基线上的 41 项检查器测试通过。其他已知差异和全量覆盖保持 `INCOMPLETE`。补丁应用位置、运行时身份及修复前后证据见[修复记录](parity/REPAIR-20260927-PAIN-VOID.md)和[源码清单](alignment/pain-void-order-manifest.json)。

应用该补丁后的[第五轮检查](parity/RESULTS-20260928-ROUND5.md)记录两类待修差异：顺劈斩／死亡收割使用疼痛触发后增加的力量计算当前牌伤害，以及鸟面瓮在疼痛失血前回血。原版反例、对照和检测入口见报告；第五轮没有修改模拟器规则。

### 群攻伤害快照与鸟面瓮回血

`aoe_urn_order.patch` 接在 `pain_void_order.patch` 后应用，重编核心、搜索和 Python 绑定。顺劈斩、戏剧性开场、燔祭、死亡收割、闪电霹雳和旋风斩在出牌时保存各敌人的整型伤害；鸟面瓮通过队首回血动作结算。伤害数组按值复制，回血使用执行分支的玩家状态。

12 个原版场景的被比较字段吻合，293 个 CTest 入口通过，冻结旧版的 41 项检查器测试通过。`slaythespire` 与 `fightsim` 使用新核心重建；8 次单次／批量战斗检查通过。补丁、运行时和证据见[修复记录](parity/REPAIR-20260928-AOE-URN.md)与[源码清单](alignment/aoe-urn-order-manifest.json)。其他规则差异与全量一致性验收保留为 `INCOMPLETE`。

该修复版的[第六轮检查](parity/RESULTS-20260928-ROUND6.md)发现消耗牌忽略能力获得顺序、红头骨致命伤复活顺序两类差异。8 个原版场景包含 3 个反例、5 个对照；观察与生产构建结果吻合。本轮增加证据与检测测试，没有修改模拟器规则，两个发现待修复。

后续 [exhaust_skull_order.patch](exhaust_skull_order.patch) 修复第六轮差异，接在 `aoe_urn_order.patch` 后应用。消耗牌复用玩家能力顺序；红头骨加减力量进入所属战斗的动作队列，回血及增加上限入口传递 `BattleContext`。12 个原版场景吻合，302 个 CTest 入口完成验证，细节与测试期望修正记录见[修复报告](parity/REPAIR-20260928-EXHAUST-SKULL.md)。

[第七轮检查](parity/RESULTS-20260928-ROUND7.md)在此基础上确认抽牌回调顺序、增加生命上限误扣红头骨力量两类新差异；8 个原版场景包含 3 个反例、5 个对照。全量一致性状态为 `INCOMPLETE`。

### 抽牌能力顺序与红头骨历史状态

[draw_skull_state.patch](draw_skull_state.patch) 接在 `exhaust_skull_order.patch` 后应用。抽牌复用能力获得顺序，虚空自身回调在能力回调之前排队；玩家保存半血和红头骨生效历史，避免增加生命上限后误判。补丁改变 `Player` 布局，核心、搜索与 Python 绑定需一起重编。

生产导出器与快照桥接新增 `is_bloodied`、`red_skull_active`。旧快照缺少字段时保留按生命推导的兼容行为，无法恢复历史；本轮更新导出器源码和隔离测试构建，没有部署到玩家安装目录。14 个原版场景的被比较字段吻合，311 个 CTest 入口完成验证；首次失败和原版证实后的测试预期修正见[修复报告](parity/REPAIR-20260928-DRAW-SKULL.md)，补丁身份见[清单](alignment/draw-skull-state-manifest.json)。

[第八轮检查](parity/RESULTS-20260928-ROUND8.md)确认撕裂与复活、残暴与混乱的两类待修差异。8 个原版场景包含 4 个反例、4 个对照，全量一致性状态为 `INCOMPLETE`。

### 撕裂与残暴的结算顺序

[rupture_brutality_order.patch](rupture_brutality_order.patch) 接在 `draw_skull_state.patch` 后应用，重编核心、搜索与绑定。撕裂加力量进入队首，在当前伤害／复活动作结束后结算；残暴先排抽牌，再排失血。修改范围为 `Player.cpp` 的两处入队顺序，动作使用执行分支的玩家状态。

第八轮 8 个原版场景的被比较字段吻合，累计修复验收覆盖 54 个原版场景，320 个 CTest 入口通过。[修复报告](parity/REPAIR-20260928-RUPTURE-BRUTALITY.md)记录新旧构建、分支隔离、可移植补丁和证据身份，[清单](alignment/rupture-brutality-order-manifest.json)记录分发文件。后续[第九轮检查](parity/RESULTS-20260928-ROUND9.md)确认负力量时突破极限绕过人工制品；复制暴走的四个受控场景吻合。全量一致性状态为 `INCOMPLETE`。

[limit_backlog_rules.patch](limit_backlog_rules.patch) 接在 `rupture_brutality_order.patch` 后，修复突破极限、两种复制效果叠加的暴走、吸血过量回血、旋风斩队列顺序与手动弃牌计数。重编核心、搜索及绑定；16 个原版记录吻合，334 个 CTest 入口通过，累计修复验收覆盖 70 个原版场景。[修复报告](parity/REPAIR-20260928-LIMIT-BACKLOG.md)、[分发清单](alignment/limit-backlog-rules-manifest.json)和[持续排查清单](parity/CONTINUOUS-AUDIT.md)记录证据与剩余范围。

[colosseum_enrage.patch](colosseum_enrage.patch) 接在 `limit_backlog_rules.patch` 后，遍历每只怪物的激怒并将加力量排入队首，修复斗技场第二个位置漏触发。重编核心、搜索及绑定；8 个原版场景吻合，343 个 CTest 入口通过，累计修复验收覆盖 78 个场景。[修复报告](parity/REPAIR-20260928-COLOSSEUM-ENRAGE.md)、[分发清单](alignment/colosseum-enrage-manifest.json)。

[ethereal_profiles.patch](ethereal_profiles.patch) 接在 `colosseum_enrage.patch` 后，修复回合结束的虚无牌消耗顺序、共享 Java RNG 延续与牌位置变化后的身份查找。配置随战斗和整局状态复制，默认对应安装的 BaseMod；`java_shared` 需要原版观察到的 48 位随机状态。重编核心、搜索及绑定；8 个本轮原版场景吻合，355 个 CTest 入口通过，累计验收覆盖 86 个场景。[修复报告](parity/REPAIR-20260928-ETHEREAL-PROFILES.md)、[分发清单](alignment/ethereal-profiles-manifest.json)保留无 Mod 整局等边界。

[ethereal_overrides.patch](ethereal_overrides.patch) 接在 `ethereal_profiles.patch` 后，补齐巩固、幽灵铠甲的批量虚无消耗回调，并在指定牌消耗后清除一次免费标志。核心、搜索及绑定重编通过；11 个原版场景吻合，366 个 CTest 入口通过，累计覆盖 97 个原版场景。[修复报告](parity/REPAIR-20260928-ETHEREAL-OVERRIDES.md)、[分发清单](alignment/ethereal-overrides-manifest.json)。

[colosseum_rng.patch](colosseum_rng.patch) 接在 `ethereal_overrides.patch` 后，修复斗技场返回事件时漏掉准备牌组的随机消耗、第二场重置房间随机状态的问题。核心、绑定及搜索模块重编通过；6 个原版场景的被比较字段吻合，374 个 CTest 入口通过，累计覆盖 103 个场景。[修复报告](parity/REPAIR-20260928-COLOSSEUM-RNG.md)、[分发清单](alignment/colosseum-rng-manifest.json)。

[bottle_choice.patch](bottle_choice.patch) 接在 `colosseum_rng.patch` 后，对齐三种瓶装遗物候选列表的顺序，保留选牌身份。10 个原版场景消除 7 个选牌反例，原始计数表示差异保留；383 个 CTest 入口通过，累计覆盖 113 个场景及状态合同。历史轨迹按牌组身份转换动作，重放 1002 条原版命令。[修复报告](parity/REPAIR-20260928-BOTTLE-CHOICE.md)、[分发清单](alignment/bottle-choice-manifest.json)。

[innate_opening.patch](innate_opening.patch) 接在 `bottle_choice.patch` 后，把超出开局抽牌数的固有／瓶装牌补抽放在百科全书战前效果之后。6 个原版场景消除 3 个手牌顺序反例；391 个 CTest 入口通过，累计覆盖 119 个场景及状态合同。原始计数表示差异保留。[修复报告](parity/REPAIR-20260928-INNATE-OPENING.md)、[分发清单](alignment/innate-opening-manifest.json)。

[astrolabe_small.patch](astrolabe_small.patch) 接在 `innate_opening.patch` 后，以原版顺序处理天体仪的小牌组候选，并修正删除后移动的下标。8 个原版场景消除 4 个变化结果反例；400 个 CTest 入口通过，累计覆盖 127 个场景及状态合同。914 个旧样本的完整观察比较相同。[修复报告](parity/REPAIR-20260928-ASTROLABE-SMALL.md)、[分发清单](alignment/astrolabe-small-manifest.json)。

[preserved_insect.patch](preserved_insect.patch) 接在 `astrolabe_small.patch` 后，使昆虫标本只降低超过上限的生命，避免抬高涅奥留下的 1 血。8 个原版场景消除 3 个反例，另补足 47 个事件／存档入战配对；411 个 CTest 入口通过，累计覆盖 182 个场景及状态合同。原始差异和覆盖缺口保留。[修复报告](parity/REPAIR-20260928-PRESERVED-INSECT.md)、[分发清单](alignment/preserved-insect-manifest.json)。

[relic_counters.patch](relic_counters.patch) 接在 `preserved_insect.patch` 后，修复小花／香炉从 −1 恢复时少算一回合及哀嚎耗尽后的计数标记。13 个原版场景消除 7 个反例；424 个 CTest 入口通过，累计覆盖 195 个场景及状态合同。茶具／哀嚎的战斗内计数表示差异保留。[修复报告](parity/REPAIR-20260928-RELIC-COUNTERS.md)、[分发清单](alignment/relic-counters-manifest.json)。

[relic_defaults.patch](relic_defaults.patch) 接在 `relic_counters.patch` 后，修复遗物获得与替换的默认计数 −1，保留九种显式零及既有正计数／失效标记。15 个原版场景消除 9 个反例；435 个 CTest 入口通过，累计覆盖 210 个场景及状态合同。NN 读取的计数维度随修复变化，旧模型胜率未重测。[修复报告](parity/REPAIR-20260928-RELIC-DEFAULTS.md)、[分发清单](alignment/relic-defaults-manifest.json)。

[shop_rewards.patch](shop_rewards.patch) 接在 `relic_defaults.patch` 后，恢复商店选牌后的同房间未领取奖励，并在进入下一地图房间时清理旧缓存。19 个原版场景的比较字段吻合；447 个 CTest 入口通过。[修复报告](parity/REPAIR-20260928-SHOP-REWARDS.md)、[分发清单](alignment/shop-rewards-manifest.json)。

[shop_purge.patch](shop_purge.patch) 接在 `shop_rewards.patch` 后，修复商店存在未领奖励时删牌过早扣款、移除卡牌的问题。24 个原版场景包含四个反例；456 个 CTest 入口通过，九处药水动作域差异保留。[修复报告](parity/REPAIR-20260928-SHOP-PURGE.md)、[分发清单](alignment/shop-purge-manifest.json)。

[shop_shared_rng.patch](shop_shared_rng.patch) 接在 `shop_purge.patch` 后，补充初始界面状态及声明帧时序下的共享随机数推进。14 个原版场景、58 个检查点消除 122 处规则字段分歧；457 个 CTest 入口通过。自然初态、其他界面操作和未附加状态路径保留缺口。[修复报告](parity/REPAIR-20260928-SHOP-SHARED-RNG.md)、[分发清单](alignment/shop-shared-rng-manifest.json)。

[shop_other_rng.patch](shop_other_rng.patch) 接在 `shop_shared_rng.patch` 后，增加药水、瓶装遗物、蛋类与会员卡操作的初态和声明帧推进。18 个原版场景、87 个检查点，458 个 CTest 入口通过；14 处药水动作域差异及后续删牌共享 RNG 缺口保留。[报告](parity/REPAIR-20260928-SHOP-OTHER-RNG.md)、[分发清单](alignment/shop-other-rng-manifest.json)。

[shop_purge_rng.patch](shop_purge_rng.patch) 接在 `shop_other_rng.patch` 后，增加删牌确认／取消、粒子与图标光效、第一幕离店背景的初态和按帧更新。23 个原版场景、124 个检查点消除 240 处规则字段差异；459 个 CTest 入口通过。奖励遗物返回商店后的三个补货反例列入待办。[报告](parity/REPAIR-20260928-SHOP-PURGE-RNG.md)、[分发清单](alignment/shop-purge-rng-manifest.json)。

[shop_reward_rng.patch](shop_reward_rng.patch) 接在 `shop_purge_rng.patch` 后，补齐药水鼎／星系仪奖励、提示列表和 Collections、回血与药水粒子、返回商店及延迟删牌的声明帧推进。22 个原版场景、190 个检查点消除 381 处规则字段差异；460 个 CTest 入口通过，23 处药水点击选项差异保留。本轮验收后按用户要求暂停。[报告](parity/REPAIR-20260928-SHOP-REWARD-RNG.md)、[分发清单](alignment/shop-reward-rng-manifest.json)。

[shop_obtain_rng.patch](shop_obtain_rng.patch) 接在 `shop_reward_rng.patch` 后，共用回血效果入口并补齐多利之镜的延迟获得、烟雾和隐藏图标更新顺序。23 个原版场景、120 个检查点消除 236 处规则字段差异；461 个 CTest 入口完成验证，首次选牌场景失败及修正后的单项重跑记录保留。本轮验收后按用户要求暂停。[报告](parity/REPAIR-20260929-SHOP-OBTAIN-RNG.md)、[分发清单](alignment/shop-obtain-rng-manifest.json)。

[shop_upgrade_rng.patch](shop_upgrade_rng.patch) 接在 `shop_obtain_rng.patch` 后，补齐磨刀石／战纹升级展示、敲击、锤印和火花的时序与共享随机消费。20 个原版场景、109 个检查点的比较字段吻合；462 个 CTest 入口通过，累计 428 个场景及状态合同。三次随机轨迹上限导致的原版失败与关闭轨迹后的重跑证据保留。本轮按用户要求暂停。[报告](parity/REPAIR-20260929-SHOP-UPGRADE-RNG.md)、[分发清单](alignment/shop-upgrade-rng-manifest.json)。


[card_obtain_callbacks.patch](card_obtain_callbacks.patch) 接在 `shop_upgrade_rng.patch` 后，修复买牌、奖励领牌、镜子复制时的遗物回调阶段及御守取消后的共享随机消费。18 个原版场景、95 个检查点；463 个 CTest 入口通过，累计 446 个场景及状态合同。用户撤销前轮暂停要求，goal 为 active。[报告](parity/REPAIR-20260929-CARD-OBTAIN-CALLBACKS.md)、[分发清单](alignment/card-obtain-callbacks-manifest.json)。


[shop_click_domain.patch](shop_click_domain.patch) 接在 `card_obtain_callbacks.patch` 后，提供原版商店点击接口并保留搜索过滤。8 个新场景及 64 个历史场景的比较字段吻合，历史 46 处药水动作域差异消除。464 个测试入口验证完成，含两项测试修正后的复测。累计 454 个场景及状态合同。[报告](parity/REPAIR-20260929-SHOP-CLICK-DOMAIN.md)、[分发清单](alignment/shop-click-domain-manifest.json)。

[reward_click_domain.patch](reward_click_domain.patch) 接在 `shop_click_domain.patch` 后，为满背包药水奖励提供校验过的点击入口，保留搜索过滤。10 个原版场景、70 个检查点吻合，7 个受阻路径获得覆盖。465 个测试入口验证完成；新夹具的两次修正及失败记录保留。累计 464 个场景及状态合同。[报告](parity/REPAIR-20260929-REWARD-CLICK-DOMAIN.md)、[分发清单](alignment/reward-click-domain-manifest.json)。

[hp_loss_relic_order.patch](hp_loss_relic_order.patch) 接在 `reward_click_domain.patch` 后，保留百年积木与符文立方体掉血抽牌的获得顺序，修复日晷／虚无导致的能量及旋风斩伤害差异。10 个原版场景、42 个检查点，3 个反例消除、7 个对照保留；467 个 CTest 入口首轮通过，累计 474 个场景及状态合同。[报告](parity/REPAIR-20260929-HP-LOSS-RELIC-ORDER.md)、[分发清单](alignment/hp-loss-relic-order-manifest.json)。

[百年积木恢复状态修复](parity/REPAIR-20260929-CENTENNIAL-RESTORE.md)导出并保留本场触发状态，受伤后缺少字段的快照拒绝导入。六个原版场景衍生 26 个恢复合同、70 个后续动作，消除 6 个差异合同。468 个 CTest 入口验证完成，首轮 467 个通过，一项历史缺失状态合同经明确分类后定向复测通过。累计 480 个场景及状态合同；[运行时](../runs/parity-repair-20260929-centennial-restore/runtime.json)，完整一致性为 `INCOMPLETE`，goal 为 active。

[发掘选牌修复](parity/REPAIR-20260929-EXHUME-SELECTION.md)保留单候选但多张消耗牌时的选择步骤，并按原版暂存、归还其他发掘牌。十个原版场景、46 个检查点、8 个选择边界消除 7 个反例。469 个 CTest 入口首轮通过，累计 490 个场景及状态合同；[运行时](../runs/parity-repair-20260929-exhume-selection/runtime.json)，完整一致性为 `INCOMPLETE`，goal 为 active。

[持续排查停止记录](parity/RESULTS-20260929-AUDIT-CLOSE.md)：R18 至 R23 六项修复／接口补全通过验收，交付沿用 R23。后续 18 个探索场景没有建立新的待修可达规则反例；人工输入差异与界面表示边界保留，候选费用补丁没有采纳。本次有限 goal 达到停止条件，完整一致性为 `INCOMPLETE`。

[升级开悟免费效果修复](parity/REPAIR-20260930-ENLIGHTENMENT-FREE.md)补充木乃伊之手和液态记忆产生的可达反例：五个费用分歧消除，九个原版场景的比较字段吻合。生产／观察／搜索运行时与 470 个回归入口、六个邻近升级探索场景的证据见修复报告，完整一致性状态为 INCOMPLETE。

[生成牌 X 费用修复](parity/REPAIR-20260930-GENERATED-X-COST.md)保留羽化生成旋风斩时的 X 费用；七个原版场景、75 个检查点消除五个反例，包含出牌、异蛇油和化学 X 后续。471 个回归入口通过；修复后四个邻近生成效果场景的比较字段吻合，完整一致性状态为 INCOMPLETE。

[自动出牌消耗与复制顺序修复](parity/REPAIR-20260930-AUTOPLAY-EXHAUST.md)解决受限出牌丢失消耗属性、时间吞噬者清理读取上一张牌、复制牌落在后续自动出牌之后的三处规则差异。18 个原版场景、163 个检查点消除 12 个反例；472 个最终回归入口通过，累计场景及状态合同为 524。修复后的四个邻近场景比较字段吻合，完整一致性状态为 INCOMPLETE。

[医疗箱／蓝蜡烛消耗标记修复](parity/REPAIR-20260930-PERSISTENT-EXHAUST.md)保留奇怪的勺子送回弃牌堆后的逐牌消耗属性，并修复结束回合移牌和中途快照恢复。12 个原版场景、98 个检查点消除七个反例，八个恢复位置的后续动作吻合。473 个回归入口通过，累计场景及状态合同为 536；修复后九个邻近场景的比较字段和逐牌属性吻合。补丁 `persistent_exhaust.patch` 接在 `autoplay_exhaust.patch` 后，快照桥接保留原版 `exhausts` 字段，完整一致性为 INCOMPLETE。
