# 原版 Java 第三版蒸馏学生验证（2026-10-01）

本轮用真实原版 Java 规则运行第三版蒸馏学生，检验其在 P300 模拟器报出的胜率是否被高估。学生只在局外决策使用一个冻结神经网络，战斗仍由共用搜索执行；未切换种子、未重试、未读档挑结果，故障单列。

## 范围与配置

- 策略：学生（`student`），`teacher_calls = 0`，不回落老师或规则。
- 模型：`distill3_frozen.pt`，SHA-256 `6b4c56eb0ff3c9820e5968bffe42df488951d76cf4c48cd15d4eb947bd63d83d`；depth=1 / width=384 / schema `31c15b49…` / 输入 11195 维。
- 运行入口：`live5`，承接 live4 的运行包与搜索配置，仅把学生代码换成第三版，并记录一次调度并发变更（4→8）。
- 游戏：本机原版 JAR 隔离逻辑实例（BaseMod、CommunicationMod、SpireLabLogic、状态审计模组），A20 铁甲，对手心脏。
- 种子：`3900020000` 起按序，目标 500 局（早期未使用的新块）。
- 口径：每局独立导入原版状态；局外决策逐条与训练加载器做 float32 位校验（`bitwise_equal=true`）。

## 结果

- 终局 473 局：231 胜 / 242 负，**完成局胜率 48.8%**。
- 95% bootstrap 区间（20000 重采样）：**[44.4%, 53.5%]**。
- 故障 34 局（占尝试 6.7%），单列不计胜负。

## 与 P300 对比

第三版在 P300 模拟器开发块（`3900041000–`）报学生 51.2%。本轮得分 48.8%，差值 **−2.4 个百分点**，95% 区间覆盖 51.2%，因此**没有证据表明 P300 的 51.2% 被显著高估**；两者在本轮样本下统计一致。

注意：本轮种子块（`3900020000–`）与 P300 评估块不同，属**跨块描述性对比**，不是同种子配对，不能表述为学生版本的因果变化。

## 故障构成（单列，不重跑）

34 局故障以桥接导入器缺口为主：

- `unmapped original queued action: ApplyPowerAction` ×10、`GainEnergyAction` ×4（未映射的原版排队动作）；
- `multi-card selection lacks its original confirmation` ×6；
- `missing GameContext continuation` ×6；
- `snapshot monster count exceeds simulator capacity` ×2；
- 其余各 1：仅支持战斗开始队列、IndexError、`VictoryRoom` KeyError、启动命令超时。

这些是导入器覆盖不足，与冻结模型、并发数无关（相关局 `teacher_calls=0`，已有决策 `bitwise_equal=true`）。故障剔除会产生选择偏差，本轮不把故障计为败局。

## 边界

- 不是锁定的未见种子验收块；本轮为开发块内的 500 局。
- 运行包含一次调度并发变更（4→8），已版本化记录；模型、种子与策略未变。
- 未做分歧对胜负的因果实验，未做逐帧状态等价声明。
- 原版 JAR、存档与逐局证据不随 Git 分发；配套 JSON 记录逐局结果与故障清单。

详见配套 `live-original-distill3-student-20261001.json`。
