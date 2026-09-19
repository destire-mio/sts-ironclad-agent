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
