# RNG 导出与原版验证运行入口

工作目录：`/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-live-original`。

本入口没有运行 P300，不用于计算胜率。它从本机已有安装及采集工具创建独立原版实例，执行自然开局至首战的一段输入，保存响应并退出。每次采集目录必须不存在，旧证据不会被覆盖。

## 重新运行有限采集

```sh
cd /Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-live-original
PYTHONDONTWRITEBYTECODE=1 \
  /Users/destire/Documents/Codex/2026-09-10/new-chat-2/outputs/spire-lab/.venv/bin/python \
  steam/rng_preflight.py \
  --oracle /Users/destire/Documents/ChatGPT/sljt/ironclad-alignment/oracle \
  --seed 5100000000 \
  --roundtrip \
  --out runs/rng-preflight-repeat-01
```

退出码 `0` 表示本段观察的 16 个持久 RNG 导出通过；指定 `--roundtrip` 时，原版 JVM 后续随机数对照也必须通过。退出码 `2` 表示导出契约有缺口；不是一场败局。发生原版启动、命令、种子、观察推进 RNG 或后续随机数错误时，脚本以异常退出，错误保存在 `result.json`。脚本不会尝试截取或关闭用户正在玩的游戏。

`--roundtrip` 在独立诊断 JVM 中采样原随机源与根据导出重建的副本，并在 `finally` 中恢复原随机源；这项测试不是普通游戏存档的 SL，也不验证整局状态恢复。Gaussian 缓存纳入导出，未知随机源子类或反射失败产生 `complete=false`，消费者据此拒绝继续。

依赖包括原有 `spire_lab` Python 环境、`ironclad-alignment/oracle`、`acceptance-expanded/common.py`、`repair-j5/candidate/instance` 以及本机 Java 8 编译运行工具。外部辅助文件的哈希记录在实例 `identity.json`；它们是只读输入。编译产物、JAR 副本、存档与偏好写入采集目录内的 `original/instance`。默认读取该隔离配置，不修改 Steam 安装目录。

`--profile without-consistent-ethereal` 是原 parity 工具提供的诊断选项：在此次隔离 BaseMod 副本中移除特定的虚无牌洗牌补丁。它不是无 Mod 运行模式。本次证据使用默认 `installed`。

## 不启动游戏，复查已有日志

```sh
cd /Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-live-original
PYTHONDONTWRITEBYTECODE=1 \
  /Users/destire/Documents/Codex/2026-09-10/new-chat-2/outputs/spire-lab/.venv/bin/python \
  steam/rng_preflight.py \
  --analyze runs/rng-fix-20260927-v1/original/observations.json.gz \
  --out runs/rng-preflight-audit-repeat-01.json
```

`--out` 在此模式下是新 JSON 文件，不能复用现有文件。摘要检查自然涅奥与战斗观察是否存在，逐观察点验证字段、精度、独立读取结果和旧战斗接口。通过范围是 16 个持久随机源；不将此结果认定为全部状态恢复或整局一致性证明。旧采集路径 `runs/rng-preflight-20260927-installed/` 保留为修复前反例，使用它会返回退出码 `2`。

原版前后夹具与回归：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s steam/tests -v
```

`steam/tests/fixtures/provenance.json` 记录同种子、同输入的修复前后原始观察来源哈希。夹具包含 RNG 数值与位置，不包含原版 JAR、反编译源码或存档。

查看命令及观察位置：

```sh
python3 - <<'PY'
import gzip, json
from pathlib import Path
p = Path('runs/rng-preflight-20260927-installed/original/observations.json.gz')
with gzip.open(p, 'rt') as stream:
    rows = json.load(stream)
for row in rows:
    request = row['request']
    game = row['response']['result'].get('game', {})
    print(request, game.get('floor'), game.get('screen_type'))
PY
```

该日志保留全部收到的原始响应，不能补回未导出的字段。命令可按顺序重新执行；完整状态与 RNG 的逐步重放一致性仍需后续验证。

## 继续 20 局之前的必要验收

1. 维持已验证的地牢 13 条 RNG、涅奥 RNG、两个共享源导出；扩展新随机源时更新契约与原版对照。
2. 绑定本机 JAR、运行时 Mod、父网络、P300 数据文件、`sv_choice`、阶段价值计算及实际加载的 native 模块哈希。
3. 对照原版导出的状态验证模拟器导入；同一真实动作在两侧执行后，比较 RNG、牌堆顺序、血量、能力、遗物计数、怪物状态与选择状态。导入失败是接入错误，不是游戏失败。
4. 验证房间存档与 SL 后的恢复边界，记录每次读取及实际分支，不将普通 SL 当作共享随机源快照。
5. 用目标 arm 的 ScumSearch、boss 倍率、rest、reuse、svsel、svcard 接入自然整局；旧 `live_model_bridge.py` 的 Arm G + MCTS 不满足此项。
6. 预注册 20 局种子，限制模拟器决策进程数不超过 3，每步落盘。遇到进程故障或无法映射的操作时，记录未完成局，不计入败局；自然终局单独计数。

没有创建运行 20 局的入口，也没有设置后台任务或定时任务。当前可执行入口的职责止于 RNG 前置检查。
