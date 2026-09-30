# 可选战斗价值网络

本目录的 `source/` 是 arena 原生核心的来源快照；来源路径和 SHA256 位于 `runs/combat-valuenet-20260927/import-provenance.json`。`source/` 中的搜索器含本轮可选 hook。`slaythespire`、`fightsim`、`combat_value` 链接同一 `sts_core`，禁止混用其他工作树的原生模块。

## 构建

在本工作树根目录执行。构建并发为 1，验收工作进程上限为 3。

```sh
PY=~/Documents/Codex/2026-09-10/new-chat-2/outputs/spire-lab/.venv/bin/python
ROOT=<repo-parent>/sts-rl-agent-valuenet
cmake -S sim_patch/combat_value -B runs/combat-valuenet-20260927/build \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=/usr/bin/c++ \
  -DSTS_JSON_INCLUDE="$ROOT/runs/combat-valuenet-20260927/json" \
  -DPython_EXECUTABLE="$PY" \
  -Dpybind11_DIR="$($PY -m pybind11 --cmakedir)"
cmake --build runs/combat-valuenet-20260927/build -j 1
python3 agent/combat_value_package.py
```

编译使用 O3、M4、FullLTO，保留断言；本轮没有 PGO。来源 arena 包使用 PGO，默认动作一致性与计时条件分别核对。运行包的 `value-build.json` 记录三个模块、核心静态库和源码哈希；`manifest.json` 绑定局外父模型与配置。重建会改变运行身份，已有采样／验收清单不允许换身份续写。

## 搜索契约

- `prior`：预测值引导 UCT，强度为 `2*(V-0.5)/sqrt(1+n/32)`。每个经重建的叶子和新展开后状态取得自己的先验。保留子树时保留先验。
- `rollout`：rollout 前两次决策各有 50% 概率比较全部合法动作的后状态价值，其余决策使用原有随机／专家排序采样。树内合法动作集合不变。
- `V = 0.8*p(win) + 0.2*E(remaining_HP/maxHP)`。模型是 512→32 ReLU→2 sigmoid，特征提取和推理使用 C++。
- 两种模式均保留复用子树。网络值不能成为终局缓存，也不能替代能执行的终局动作序列。战斗结果来自规则引擎执行，推理未介入默认模式。
- 一个模型对象在单进程内复用。Python 入口不释放 GIL；工作并行使用独立进程，各进程有独立树和模块锁。

## 入口

`P300_ENGINE=valuenet` 选择本工作树的同核运行包。arm 的 `valuenet` 与 `reuse/refine/fast/adaptN` 互斥；`simsN/bossN/rest/svsel/svcard` 可组合。`P300_VALUE_MODEL` 指定模型 JSON，`P300_VALUE_MODE` 为 `prior` 或 `rollout`。

`valuenet` 在第二幕 Boss、第三幕楼层不低于 50 的 Boss 和心脏启用模型；其他战斗走复用模式。这避免将晚期 Boss 标签外推到普通战和第一幕。默认 `P300_ENGINE=arena` 与原有 arm 路径保持原行为。

示例配置：

```sh
export P300_ENGINE=valuenet
export P300_VALUE_MODEL=<repo-parent>/sts-rl-agent-valuenet/runs/combat-valuenet-20260927/model/value.json
export P300_VALUE_MODE=prior
# arm: sims32+boss12+rest+valuenet+svsel+svcard
```

是否可以采用，以 `docs/combat-valuenet-20260927.md` 的验收结论为准。单场门槛通过前不启动整局测试。整局确认预留种子起点为 5000000000，两臂各 512 局。

## 复核入口

`combat_value_prepare.py` 冻结来源与家族划分；`combat_value_train.py` 负责采样和模型导出；`combat_value_accept.py` 负责墙钟对照和家族聚类置信区间；`combat_value_run.py` 只执行预先写定的两种单场设计。采样故障、未终局和结果回放失败不会计为输局。

`combat_value_check.py` 核对默认动作和终局回放；`combat_value_entry_check.py` 核对 P300 互斥、目标战斗路由和普通战复用；`prior_contract.cpp` 的反例检查能检出遗漏兄弟节点先验的问题。作废记录保存在 `invalid-prior-hook-v1/`，不能用于验收。
