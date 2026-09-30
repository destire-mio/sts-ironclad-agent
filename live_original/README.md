# 原版 Java 对接（live4）

统一入口是本目录 `run.sh`。老师接 live3 的 100 个固定种子；学生接 32 个固定种子。所有尝试保留：故障、中断、胜、负均不重试。原版是状态与终局的依据，战斗每个实际状态规划一次。

## 启动与状态

老师（3900012000–3900012099，跳过已有尝试）：

```sh
<repo>/live_original/run.sh --policy teacher
```

学生（冻结第二版）：

```sh
<repo>/live_original/run.sh --policy student --model <repo>/live_original/live4/models/distill2_frozen.pt
```

学生默认集合为 3900016000–3900016031。前 16 个种子在 live3 使用第一版 `selected.pt`；入口引用这些历史结果，第二版执行未尝试的后 16 个。合计 32 局不代表第二版获得 32 局证据。报告按模型、运行包、Java 观察器和导入器分组，不用此样本判断学生胜率。

```sh
./run.sh --policy teacher --status
./run.sh --policy student --status
./run.sh --policy teacher --drain
./run.sh --policy student --drain
```

`--drain` 停止开新局，让在途对局到终局；Ctrl-C/TERM 采用相同方式。重复启动命令恢复未尝试种子。默认调度 8 小时，`--hours 24` 延长开局窗口，不构成单局超时。断电等中断记为 fault，续跑跳过该种子。

`--workers 1..4` 是并行上限。入口计入其他 Java 进程，按磁盘余量缩减并行，为每个在途实例预留 350 MB，保留 3 GB。磁盘余量不足时停止开新局；确认空间恢复后用同一命令续跑。`--out` 必须在本目录下；固定批次不通过缩小 `--games` 续跑。新批次的 `--seed N --games K --out PATH` 必须使用获授权的种子，不使用锁定 1024 验收块。

## 模型契约

第二版模型 SHA-256：`90b937349181b165a1d3281f03481e92e221c915869627ef6e9fa9e4e094fa2b`。

推理采用云端 `distill2-code-v1` 的 `load_student(path, encoder=...)` 和 `choose(gc, actions, descriptors)`。模型旁须有 `freeze.json`；载入时核对模型 SHA、schema ID 和本机编码器生成的完整 schema。第三版沿用同一 checkpoint 格式、schema 和接口时，替换 `--model PATH` 可加载；既有输出目录绑定旧模型，不能改写，另设 `--out` 并指定获授权的未尝试种子。

学生在 eval 模式，参数禁止梯度更新。局外候选由网络 argmax 选择，并列选传入列表首项。每次局外决策从同一原版导入状态独立提取两份候选，经过生产训练 CSR Writer 与 Dataset.batch，比较六组 float32 输入的位模式和 11195 维特征。检查包含候选顺序、公共字段过滤、路线与候选上下文。检查失败记 fault，不退回老师或规则。

老师选择入口、局外规则函数及父模型各层 choose 有报错保护；计数写入结果。对话推进、界面确认属于动作传输。战斗由共用搜索执行。离线检查覆盖保存的原版导入状态与训练特征路径，不代表独立原版／模拟器整局一致。

## 运行包与版本边界

老师源于云端 v21，开关：

```
sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4
```

普通战 40000、心脏 80000、盾矛 320000，Boss 倍率 12。Java 堆上限 384 MB。原版每个实际搜索根规划一次；执行分歧后从新的原版状态继续，不回滚、不挑选搜索结果。

- 老师 3900012000–3900012011：live3 初始导入器；3900012012–3900012014：形状怪导入修复；后续：live4 运行包。
- live3 学生 16 局：旧计数观察器与旧导入器。live4 第二版学生：修复后的观察器、形状怪导入器和运行包。
- live4 修复时间吞噬者强制结束回合时的陀螺抽牌顺序。原版 `callEndTurnEarlySequence → releaseCard → refreshHandLayout` 可在结束回合前排入抽牌，旧核心漏掉此步骤。保存动作验证：目标 30 处差异降至 0，其余 50 个对照结果未改变，其中 9 个保留已有差异。见 `live4/evidence/top-repair-verification.json`。

live3 源码、模型与已完成结果保留。派生包在 `live4/runtime/`，版本绑定见 `live4/runtime-history.json` 和 `live4/delivery-manifest.json`。修复后的原版结果与云端 c42 历史结果配对时展示版本分组；不能称为 100 局同一冻结版本验收。

## 文件与审计

- 老师：`live3/teacher/summary.json`、`progress.json`、`<seed>/result.json`。
- 学生：`live4/student/summary.json`；历史组的证据仍在 `live3/student/`。
- 单局：`terminal.json.gz`、`steps.jsonl.xz`、`plans.jsonl.xz`、`decisions.jsonl.xz`、`original/rpc.jsonl.xz`，保留命令、状态和搜索根。
- 模型及来源：`live4/models/`、`student-code/`、`evidence/cloud-local-student-source.json`。
- 训练特征检查：`live4/evidence/student-preflight.json`；云端学生配对范围：`evidence/cloud-student-pairing.json`。
- 资源采样：`live4/evidence/resource-samples.jsonl`。历史 live1/live2 日志与实例目录经过无损压缩；实例内容位于原 `original/instance.tar.xz`，逐文件 SHA 清单在 `historical-instance-archives.json`。历史结果、动作与状态未删除。

批次结束后审计：

```sh
python <repo>/live_original/live4/audit.py
```

审计检查原版种子/A20/心脏胜利标志、一次自然开局、禁止读档 RPC、重复搜索根、战斗预算、模型及特征检查、版本清单与 Java 清理。故障单列，不当作自然败局。

调度器退出后可执行 `./run.sh --cleanup`，清理范围限于本任务 live3/live4 的隔离实例。运行不访问云端；本轮云端操作为下载模型、代码及结果范围清单，没有云端实验、资源修改或 Git 发布。

环境：Apple M4、Python 3.12，默认解释器 `python`；可用 `LIVE_PYTHON` 指定兼容环境。依赖 torch、numpy、pybind11、spire_lab 及本机原版游戏/ModTheSpire。最终结果入口：`../../scratchpad/parity/live4-report.md`。
