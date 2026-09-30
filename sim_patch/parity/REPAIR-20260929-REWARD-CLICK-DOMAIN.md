# 满背包时的药水奖励点击

原版 CommunicationMod 允许点击药水奖励，即使背包满。普通满背包点击会保留奖励、显示固定提示并推进界面；添水会移除奖励，但不会获得药水。模拟器搜索过滤这些普通满背包操作，旧检查器因而拒绝原版命令，缺少对应的核心执行入口。

本轮为 `GameContext` 增加 `claimPotionReward(index)` 及 Python 的 `claim_potion_reward(index)`，检查器调用此入口。搜索过滤规则保留。接口返回奖励是否被移除：普通满背包返回 false，空位领取及添水返回 true。原有奖励动作复用此方法，奖励槽位、画面效果和随机数在同一条路径更新。非法槽位、错误界面、终局、空奖励及缺少时钟的操作在状态写入前拒绝。

满背包点击使用原版固定药水提示，不消耗随机提示，也不触发提示池重填。获得药水才消耗获得音效对应的随机数；添水与背包满分别保留各自的奖励结果。没有增加游戏状态字段。[补丁](../reward_click_domain.patch)接在 `shop_click_domain.patch` 后，[分发清单](../alignment/reward-click-domain-manifest.json)绑定五个核心文件。两个便携源码变体零模糊匹配应用，各完成四个翻译单元的语法检查。

10 个独立原版场景包含 70 个检查点、60 个 native 动作和 80 条普通原版命令。覆盖满背包、空槽、添水、连续点击、不同奖励位置、丢弃后领取、1／64 帧时钟，以及开启／关闭随机轨迹的对照。60 个动作完成复制分支检查。原版后态不参与模拟器初始化或执行。

R19 在其中 7 个场景返回 `worker_error`，3 个对照完成重放且比较字段吻合。前者证明操作尚未支持，不能算作错误后态的反例。修复后生产与观察构建的 10 个场景比较字段吻合，输出相同；7 个受阻路径获得执行覆盖。原版采集错误为零，10 个实例完成收尾。原始错误及对照保留在[分类记录](../../runs/parity-repair-20260929-reward-click-domain/classification.json)。

465 个 CTest 入口完成验证：首轮 464 个通过，新边界测试因夹具未满足“新商店”初始化约束而失败。第一次修正了房间类型，复测发现奖励容器仍不为空；清空初始化时的奖励容器并在附加界面状态后恢复奖励，定向复测通过。核心源码没有为两次复测改动，首轮及失败复测的输入和日志保留。

本轮五个测试方法检查 8 个错误后态、1 个错误时钟、9 项非法调用、满背包与添水的区别、搜索过滤和 Python 入口。历史自然轨迹的 1002 条命令及 837 个被比较检查点吻合，终局为第 51 层失败、1786 分。8 个搜索样本通过顺序执行、1／4 线程批量执行和副本隔离。

[运行时身份](../../runs/parity-repair-20260929-reward-click-domain/runtime.json)、[验收记录](../../runs/parity-repair-20260929-reward-click-domain/verification.json)、[原版夹具](tests/fixtures/reward-click-domain-original.json.gz)、[场景输入](specs/reward_click_domain_round38.json)和[源码依据](../../runs/parity-repair-20260929-reward-click-domain/source-audit.json)提供复查入口。累计证据为 464 个场景及状态合同。工作位于隔离 worktree，提交、推送和主工作树修改次数为零，goal 为 active。

场景分类保留 `coverage_gap`：自然商店入口、任意帧节奏、其他奖励界面的表现、其他原始 UI 命令、全部私有字段和无 Mod 参考尚缺覆盖。源码排除了终局动作泄漏、Prayer Wheel TODO 及无调用的空牌组变化候选，见[排除记录](../../runs/parity-repair-20260929-reward-click-domain/excluded-hypotheses.json)。本轮不宣称完整一致。
