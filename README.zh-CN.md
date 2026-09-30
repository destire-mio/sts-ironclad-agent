<div align="center">

# sts-ironclad-agent

**杀戮尖塔 A20 铁甲战士打牌程序：局外决策规则加模拟器战斗搜索，心脏局胜率约 50%。**

[English](README.md) | 中文

</div>

基于 [sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed)，延续自
[Jialeiv/sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent)。目标是让铁甲战士在进阶 20 下拿齐三把钥匙并击败心脏，
局外的每个选择都来自一个冻结网络，只有战斗搜索可以保留传统算法。

## 结果

| 版本 | 种子 | 局数 | 心脏局胜率 |
|---|---|---:|---:|
| P300 老师（`agent/p300_play_v21.py`） | 开发种子 | 2,000 | **50.1%** |
| P300 老师 | 新种子 | 1,000 | **49.5%** |
| 蒸馏学生网络（[`student/`](student/README.md)） | 开发块 3900040000+ | 1,000 | 50.2%（同种子老师 54.7%） |

以上都是固定种子下的模拟器测量，不是原版胜率。蒸馏学生网络的 1,024 未见种子最终验收还没有运行，它的 50.2% 只是开发块数字。

剩余的死亡分布（3,000 局，按进入该阶段的局计死亡率）：

| 第一幕路上 | 第一幕 Boss | 第二幕路上 | 第二幕 Boss | 第三幕路上 | 第三幕两个 Boss | 盾矛 | 心脏 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 9.1% | 1.9% | 10.3% | 5.1% | 4.3% | 9.3% | 3.7% | 21.3% |

心脏这一战主要由牌组和进场血量决定：血量 ≥75% 时赢 90%，<50% 只赢 31%，加搜索预算没有用。
详情和被否决的实验见 [`docs/status-2026-09-30.md`](docs/status-2026-09-30.md)。

## 工作方式

1. **决策层**：地图、选牌、商店、篝火、事件、遗物由规则和模拟器实验得到的价值表决定；正在把它蒸馏成一个网络学生。
2. **战斗**：由模拟器搜索打每一场（基础 32 倍预算，Boss 加预算，子树复用）。引擎源码在 [`combat_engine/`](combat_engine/combat4r/)。
3. **评测规则**：只用固定种子；不换种子，不重试挑结果，不对同一决策重复搜索；验收数字必须来自未见种子。

## 与原版游戏的一致性

模拟器带有补丁（[`sim_patch/`](sim_patch/README.md)）和一个在真实游戏里重放场景的检查器（[`sim_patch/parity/`](sim_patch/parity/README.md)）。
九轮排查发现并修复了几十处规则差异，但一致性仍是 **`INCOMPLETE`**：上面的模拟器胜率不能当作原版胜率。
与真实游戏的在线对接保存在 `live-original-bridge` 分支。

## 目录

| 路径 | 内容 |
|---|---|
| `agent/` | 程序代码：老师驱动（`p300_play_v21.py`、`p300_play_v24.py`）、公共函数、蒸馏与心脏研究工具 |
| `student/` | 蒸馏学生网络（17MB 权重、代码、接口说明） |
| `experiments/combat_value/` | 战斗价值网络实验（仅脚本，不属于老师） |
| `combat_engine/` | 战斗引擎源码快照，以及战后 HP 评分报告 |
| `runtime/` | 冻结的父网络、配置和运行文件（引擎编译到 `runtime/engine/`） |
| `data/` | 老师读取的阶段价值表 |
| `scripts/` | `setup.sh`、`run_teacher.sh`、`assemble_runtime.py` |
| `sim_patch/` | 模拟器补丁、原生对齐测试、原版一致性检查器 |
| `steam/` | 真实游戏状态导出与在线搜索 |
| `experiments-archive/` | P200-P212 与云端 c5-c52 的报告和结果 |
| `docs/` | [当前状态](docs/status-2026-09-30.md)、[历史记录](docs/history.zh-CN.md)、685 份实验记录、经验总结 |
| `tests/` | 回归测试（需要编译好的 `slaythespire` 模块和 PyTorch） |
| `weights/` | 历史小模型权重 |

## 快速开始

需要 Python 3.12、`cmake` 和支持 C++17 的编译器（在 macOS arm64 上测试）。引擎源码、父网络、价值表都在本仓库里。

```bash
scripts/setup.sh                 # 建虚拟环境、装 numpy/torch/pybind11、编译引擎、生成运行包标识文件
scripts/run_teacher.sh 4 4       # 用当前老师打 4 局，4 个进程
```

`run_teacher.sh [局数] [进程数] [起始种子] [输出文件]` 每局写一行 JSON，并打印胜场。单核一局约一分钟，重复运行会续跑。
想要可信的胜率，请用没调过参的种子块（开发块是 3900012000 起）。

上次整理时验证：全新编译的引擎在种子 3900012000 上 45 秒打到了心脏（第 56 层），没有引擎故障；云端老师在同一种子上到了同一层。
长跑胜率没有用这个构建重新测。

还不是一键的部分：蒸馏学生在仓库里没有整局驱动（只有加载接口，见 `student/INTERFACE.md`）；
接原版游戏需要你自己的游戏和 Mod（见 [`docs/live-original-runbook.md`](docs/live-original-runbook.md)）；测试需要编译好的引擎和 PyTorch。
旧版 A0 策略的复现方法见 [`docs/history.zh-CN.md`](docs/history.zh-CN.md)。

## 致谢与协议

- 模拟器：[gamerpuppy/sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed)（MIT）。
- 真实游戏桥接：[CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod)、[ModTheSpire](https://github.com/kiooeht/ModTheSpire)、[BaseMod](https://github.com/daviscook477/BaseMod)。
- 本仓库：MIT，见 [`LICENSE`](LICENSE) 与 [`docs/acknowledgements.md`](docs/acknowledgements.md)。
  《杀戮尖塔》是 Mega Crit Games 的商标，本项目是非官方研究项目。
