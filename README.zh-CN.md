<div align="center">

# sts-ironclad-agent

**杀戮尖塔 A20 铁甲战士打牌程序：局外决策全部来自一个冻结网络，战斗用模拟器搜索——模拟器和真实游戏的心脏局胜率都在 50% 左右。**

[English](README.md) | 中文

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Heart win rate ~50%](https://img.shields.io/badge/%E5%BF%83%E8%84%8F%E8%83%9C%E7%8E%87-~50%25-green.svg)](#结果)
[![Simulator parity: incomplete](https://img.shields.io/badge/%E6%A8%A1%E6%8B%9F%E5%99%A8%E4%B8%80%E8%87%B4%E6%80%A7-INCOMPLETE-red.svg)](#模拟器与原版游戏)

</div>

基于 [sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed)，延续自
[Jialeiv/sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent)。目标是让铁甲战士在进阶 20 下拿齐三把钥匙并击败心脏，
局外的每个选择都来自一个冻结网络，只有战斗搜索保留传统算法。纯模拟器子集已单独发布为
[sts-ironclad-simulator](https://github.com/destire-mio/sts-ironclad-simulator)。

## 结果

| 场景 | 策略 | 种子 | 局数 | 心脏胜率 | 95% 区间 |
|---|---|---|---:|---:|---:|
| 模拟器 | P300 老师（`agent/p300_play_v21.py`） | 开发种子 | 2,000 | 50.1% | — |
| 模拟器 | P300 老师 | 新种子 | 1,000 | 49.5% | — |
| 模拟器 | 蒸馏学生（[`student/`](student/README.md)） | 开发块 3900040000+ | 1,000 | 50.2% | — |
| **真实游戏** | **蒸馏学生（第三版）** | 全新块 3900020000+ | 501 | **50.1%** | [45.7, 54.5] |

- **模拟器** = 固定种子下的模拟测量；**真实游戏** = 原版 Java、A20 打心脏，战斗保留搜索，局外由一个冻结网络决定，故障单列。
- 真实游戏数字 = 首轮 473 局，加上它的 34 个桥接故障种子在修复后的导入器上重跑（28 终局，6 仍故障）；修复只改桥接，不改策略。
- 区间覆盖了模拟器估计，因此本轮**没有证据说明模拟器数字被高估**。
- 评测规则：固定种子，不换种子、不重试、不对同一决策重复搜索；锁定的 1,024 未见种子验收还没有运行。
- 原版报告与逐局数据：[`docs/live-original-distill3-student-20261001.md`](docs/live-original-distill3-student-20261001.md)。

剩余死亡分布（模拟器，3,000 局，按进入该阶段的局计死亡率）：

| 第一幕路上 | 第一幕 Boss | 第二幕路上 | 第二幕 Boss | 第三幕路上 | 第三幕两个 Boss | 盾矛 | 心脏 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 9.1% | 1.9% | 10.3% | 5.1% | 4.3% | 9.3% | 3.7% | 21.3% |

## 工作方式

1. **决策层** —— 地图、选牌、商店、篝火、事件、遗物由老师蒸馏出的一个冻结网络决定。
2. **战斗** —— 模拟器搜索（`sims32`，Boss 加预算，子树复用）；引擎源码在 [`combat_engine/`](combat_engine/combat4r/)。
3. **评测** —— 只用固定种子；验收数字必须来自未见种子。

## 模拟器与原版游戏

模拟器带有补丁（[`sim_patch/`](sim_patch/README.md)）和一个在真实游戏里重放的原版一致性检查器
（[`sim_patch/parity/`](sim_patch/parity/README.md)）。一致性仍是 **`INCOMPLETE`**——桥接在一批排队动作上还会故障，
因此不是逐动作复现；但上面首次原版运行的胜率与模拟器在区间内一致。当前桥接修复源码位于 `main`，见 [原版导入器修复与验证范围](docs/original-importer-repairs-2026-10-01.md)。`live-original-bridge` 分支保留历史接入基线。

[后续复审](docs/original-importer-followup-2026-10-01.md) 记录冻结运行包版本差异、钢笔尖队列与计数修复，以及三个故障种子的诊断重跑。

## 目录

| 路径 | 内容 |
|---|---|
| `agent/` | 老师驱动（`p300_play_v21.py`、`p300_play_v24.py`）、蒸馏与心脏研究工具 |
| `student/` | 蒸馏学生网络（权重、代码、接口说明、`play_student.py`） |
| `live_original/` | 在真实游戏里跑老师和学生的脚本（路径待适配） |
| `combat_engine/` | 战斗引擎源码，以及战后 HP 评分报告 |
| `runtime/` | 冻结的父网络、配置和运行文件（引擎编译到 `runtime/engine/`） |
| `data/` | 老师读取的阶段价值表 |
| `sim_patch/` | 模拟器补丁、原生对齐测试、原版一致性检查器 |
| `steam/` | 真实游戏状态导出与在线搜索 |
| `docs/` | [当前状态](docs/status-2026-09-30.md)、[历史记录](docs/history.zh-CN.md)、实验记录 |
| `experiments-archive/` | P200-P212 与云端 c5-c52 的报告和结果 |
| `scripts/` | `setup.sh`、`run_teacher.sh`、`assemble_runtime.py` |
| `tests/` | 回归测试（需要编译好的 `slaythespire` 模块和 PyTorch） |

## 快速开始

需要 Python 3.12、`cmake` 和支持 C++17 的编译器（在 macOS arm64 上测试）。引擎源码、父网络、价值表都在本仓库里。

```bash
scripts/setup.sh                 # 建虚拟环境、装 numpy/torch/pybind11、编译引擎、生成运行包标识文件
scripts/run_teacher.sh 4 4       # 用当前老师打 4 局，4 个进程
scripts/run_student.sh 4 4       # 同样，但局外决策由蒸馏学生网络做
```

`run_teacher.sh [局数] [进程数] [起始种子] [输出文件]` 每局写一行 JSON 并打印胜场；单核一局约一分钟，重复运行会续跑。
想要可信的胜率请用没调过参的种子块（开发块是 `3900012000+`）。全新 CMake 构建不能一步不差复现云端对局（交付版用了 PGO/LTO），
请你重跑足够多的局之前把它的胜率当作未测量——见 [`combat_engine/combat4r/report.md`](combat_engine/combat4r/report.md)。
原版游戏运行脚本在 [`live_original/`](live_original/PORTING.md)（保持运行时的样子；需要你自己的游戏和 Mod）。

## 致谢与协议

- 模拟器：[gamerpuppy/sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed)（MIT）。
- 真实游戏桥接：[CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod)、[ModTheSpire](https://github.com/kiooeht/ModTheSpire)、[BaseMod](https://github.com/daviscook477/BaseMod)。
- 本仓库：MIT，见 [`LICENSE`](LICENSE) 与 [`docs/acknowledgements.md`](docs/acknowledgements.md)。
  《杀戮尖塔》是 Mega Crit Games 的商标，本项目是非官方研究项目。
