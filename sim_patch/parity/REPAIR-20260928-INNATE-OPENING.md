# 2026-09-28 固有牌开局补抽顺序修复

当固有牌和瓶装牌数量超过开局抽牌数时，模拟器先补抽，再执行百科全书生成能力牌。原版先处理百科全书的战前动作，再补抽。7 张固有牌的复现中，原版生成的狂暴位于手牌第 1 张，模拟器位于第 3 张。

## 原版证据与修改

`CardGroup.initializeDeck` 将超过 `masterHandSize` 的抽牌数放入 `preTurnActions`。`AbstractPlayer.preBattlePrep` 随后调用遗物的 `atPreBattle`；百科全书把生成能力牌放入普通动作队列。`GameActionManager.getNextAction` 先执行普通队列，再执行 `preTurnActions`，之后进入常规开局抽牌与战斗开始效果。[源码记录](../../runs/parity-repair-20260928-innate-opening/source-audit.json)。

模拟器在 `CardManager.init` 中排入补抽，早于 `BattleContext.initRelics` 排入百科全书动作。[补丁](../innate_opening.patch)让牌组初始化返回补抽数量，由战斗初始化在战前效果后排队。没有新增持久状态，也没有新增抽牌或随机数调用。补丁接在 `bottle_choice.patch` 后，涉及两个实现文件及其声明。

6 个独立原版 JVM 覆盖超过阈值的固有牌、异蛇之眼改变抽牌阈值、瓶装牌计入开局牌，以及无百科全书、等于阈值、扭曲之钳对照。[输入](specs/innate_opening_round17.json)、[不可变捕获](tests/fixtures/innate-opening-original.json.gz)、[来源与清理](tests/fixtures/provenance.json)。原版初态用于建立双方相同输入，后续结果只作比较。

| 验证 | 结果 |
|---|---|
| 6 个原版场景 | 3 个手牌顺序反例消失，3 个对照吻合；生产与观察构建均核对顺序、升级状态、战斗字段、牌组与 7 组 RNG |
| 原始表示差异 | 4 个场景保留 `counter=-1` 对 `data=0`，报告为 `observation_difference`；其余 2 个为 `coverage_gap` |
| 7 个 C++ 专项 | 旧核心 4 失败、3 对照通过；新核心 7 通过，包含十张手牌上限、复制隔离及源牌组不变 |
| 全部 CTest | 391 个入口通过，包含历史自然整局和轨迹身份转换 |
| 累计原版修复合同 | 生产、观察构建各 36 项测试通过，累计覆盖 119 个原版场景及状态合同 |
| 检查器反例 | 冻结旧引擎的 41 项测试通过 |
| 可移植补丁 | optimized、E121 零 fuzz 应用，4 个变更翻译单元语法检查通过 |
| 搜索运行时 | 核心、绑定与搜索模块重编；8 个顺序／批量任务结果、输入 RNG 和复制隔离通过 |

[旧核心比较](../../runs/parity-20260928/round17-innate-opening-v1/comparison/report.json)、[生产比较](../../runs/parity-repair-20260928-innate-opening/replay-production/report.json)、[观察构建比较](../../runs/parity-repair-20260928-innate-opening/replay-audit/report.json)、[差异分类](../../runs/parity-repair-20260928-innate-opening/classification.json)、[专项前后对照](../../runs/parity-repair-20260928-innate-opening/focused-before-after.json)、[回归日志](../../runs/parity-repair-20260928-innate-opening/ctest.log)。

生产目录为 `runs/parity-repair-20260928-innate-opening/build`，观察构建为同级 `audit/build`。[分发清单](../alignment/innate-opening-manifest.json)、[源码及运行时身份](../../runs/parity-repair-20260928-innate-opening/runtime.json)、[交付核验](../../runs/parity-repair-20260928-innate-opening/verification.json)。上轮瓶装修复源码及二进制保留。

```bash
python -m sim_patch.parity outside \
  --engine runs/parity-repair-20260928-innate-opening/build \
  --executable runs/parity-repair-20260928-innate-opening/build/outside_probe \
  --source sim_patch/parity/tests/fixtures/innate-opening-original.json.gz \
  --out runs/innate-opening-replay-new-directory
```

观察范围不包含全部私有状态和每张牌的临时费用；原始计数差异没有被删除。原版为安装的 Mod 配置，无 Mod 原版与完整动态分支没有完成验证，一致性结论为 `INCOMPLETE`。6 个原版实例退出。goal 为 active，下一项为天体仪小牌组变化顺序，见[持续排查清单](CONTINUOUS-AUDIT.md)。没有提交、推送或修改主工作树。
