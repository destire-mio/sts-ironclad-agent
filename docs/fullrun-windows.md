# Windows 原生：整局局外 PPO 实验

这个分支让模型在完整对局中学习选牌、遗物、路线、商店、事件、休息和升级等局外选择。战斗由固定的 MCTS 执行，正式实验预算为每次搜索 8,000 次、Boss ×3。范围是铁甲战士 A20、三把钥匙、第三幕双 Boss、第四幕心脏；排除棱彩碎片。

训练从仓库附带的 E87 父模型开始，更新局外网络和价值网络的 1,074,370 个参数。每轮用当前模型采集完整对局，用心脏胜负作为奖励，再用 PPO 更新；下一轮使用更新后的模型采集新对局。没有楼层奖励，也不枚举整局的所有分支。探索使用独立随机数，不消耗游戏 RNG。

这是实验入口，尚无胜率提升结论。父模型的历史 macOS 成绩是 248/2,560；它不是本分支或 Windows 的成绩。

## 安装

需要 Windows x64、Git、64 位 Python 3.12（包含 `py` 启动器），以及 Visual Studio 2022 Build Tools 的“使用 C++ 的桌面开发”组件和 Windows SDK。安装器会创建 `.venv`、下载固定版本模拟器源码、应用仓库补丁并编译原生模块。不需要 WSL、显卡或原版游戏 JAR。

在 PowerShell 中运行：

```powershell
git clone --single-branch --branch codex/full-run-ppo-windows-20260920 https://github.com/destire-mio/sts-rl-agent.git
cd sts-rl-agent
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_fullrun.ps1 -Jobs 2
```

`ExecutionPolicy Bypass` 作用于这次 PowerShell 进程，不修改系统策略。安装完成后，所有命令使用仓库内的 Python：

```powershell
& .venv/Scripts/python.exe scripts/fullrun.py doctor
& .venv/Scripts/python.exe scripts/fullrun.py train --config configs/fullrun_smoke.json --run runs/windows-smoke-01
```

小规模检查包含 2 局训练采样、一次参数更新、模型保存与加载，以及更新前后的开发集评估。它使用降低的战斗预算，结果用于检查软件链路，不衡量胜率。

## 开始试验

```powershell
& .venv/Scripts/python.exe scripts/fullrun.py train --config configs/fullrun_windows.json --run runs/windows-fullrun-01
```

默认 4 个采样进程；10 轮，每轮 128 个新训练种子；64 个固定开发种子用于比较父模型和选择候选。按开发集胜局数选择模型，没有提升时保留父模型。CPU 上的模拟器搜索是主要计算开销。

运行前可修改 `configs/fullrun_windows.json` 中的并发和实验预算。开始后配置、代码、Python、PyTorch 与原生模块需要保持一致；变更后使用新实验目录。不要在两个终端同时写入同一个实验目录。

查看进度：

```powershell
& .venv/Scripts/python.exe scripts/fullrun.py status --run runs/windows-fullrun-01
```

正常暂停使用 Ctrl+C。再次执行相同训练命令可恢复，完整采样文件和完成的更新会被复用。每个实验目录保留模型、配置、种子、文件哈希、对局轨迹和报告。超时、崩溃、重放分歧会拒绝该批次，不当作死亡奖励；发现这些错误时检查 `error.json` 和对应轮次的 `episodes/report.json`，保存现场后排查。

## 评估边界

训练、开发和预留测试种子互不重叠，并避开打包时导出的历史种子集合。`fullrun_known_seeds.json` 是历史记录快照，不覆盖其他电脑未来产生的数据；跨电脑合并实验时需要核对种子。

完成试验后，用开发集选出的模型评估 1,024 个预留种子：

```powershell
& .venv/Scripts/python.exe scripts/fullrun.py accept --run runs/windows-fullrun-01
```

模型在测试前冻结，测试入口拒绝重复启动。报告给出完整分母、胜率和 95% Wilson 区间；达到样本 50% 不代表总体胜率下限达到 50%。所有有效对局核对终态、输入、动作和 RNG 重放；这不替代胜局重新执行 MCTS 或与原版 Java 的对照。

提交前的 macOS 检查通过：17 项原生规则/接口检查、9 项训练与重放检查，以及 2 局训练采样的完整软件流程。Windows 原生检查由本分支的 GitHub Actions 执行，状态见仓库 Actions 页面；本机 macOS 通过不代表 Windows 通过。该分支不接管原电脑正在进行的实验。
