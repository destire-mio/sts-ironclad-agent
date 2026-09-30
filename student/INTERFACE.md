# 第二版学生接口

单个 `11195 → 384 → 1` ReLU 网络对合法候选评分，返回 `argmax` 的索引。并列最高分取传入列表中的首项。推理不查询教师、不执行规则覆盖、不更新参数；战斗搜索由调用方处理。输入为空、候选不齐、非有限值或 schema 不符时抛错，不回退到规则。

## Python 对接

将本目录放入 `sys.path`。推理依赖 Python、NumPy、PyTorch，以及本目录的 `distill2_base.py`、`distill2_features.py`、`distill2_model.py`。

```python
from distill2_model import load_student

student = load_student('/absolute/path/distill2_frozen.pt', encoder=runtime.A)
index = student.choose(gc, actions, descriptors)
actions[index].execute(gc)  # 执行权在调用方
```

`encoder` 可省略，此时对 `gc` 输入导入 `armG_train`。`actions` 与 `descriptors` 必须来自同一状态、相同合法动作顺序。`actions` 每项暴露整数 `bits`；返回值是索引，不是 action bits。调用者可用 `actions[index].bits` 转换为原版动作。

现有 `parent.choose(gc, observation, actions, descriptors)` 调用点需改为上述三参数入口；不能把未过滤 observation 传给学生。

## 原版 Java 桥接

可以传入公共状态 packet，避免推理端导入模拟器：

```python
packet = {
    'schema_id': student.schema['schema_id'],
    'observation': public_observation_float32,  # 6843 项，按白名单过滤
    'extra': public_extra_float32,             # 20 项
    'routes': candidate_routes_float32,        # N × 26
}
index = student.choose(packet, ordered_action_bits, descriptors)  # N × 807
```

整数 actions 用 Python `int`。Java 端需通过已有动作桥映射为相同 bits；牌、遗物、药水等 ID 沿用冻结 runtime 枚举，不使用 Java 枚举序号替代。`schema.json` 保存偏移、缩放、卡牌类型矩阵、字段顺序及编码器 SHA。网络文件内含同一 schema，模型与 schema 无需分开传递。

状态构造函数为 `distill2_features.public_packet(gc, actions, descriptors, schema, encoder)`。可以对其返回值调用 `distill2_parity.json_packet()` 输出 JSON。网络输入按 float32 处理；不能经过 float16 或十进制截断。候选 mean/max 从 float32 descriptors 计算，由共享 Python 特征函数完成。

公共字段：HP、最大 HP、金币、楼层、幕数、坐标、牌组、遗物、药水、钥匙、公开地图、当前 Boss 图标、事件名称和界面显示的金额。额外输入含 HP 比、初始牌/升级牌/各类型计数、药水容量、删牌价格。每个地图候选包含燃烧精英位置可达性、距离、可达节点数、各房型最近距离、路径房型计数的最小/最大值。字段的精确名称与顺序见 `schema.extra_names`、`schema.route_names`。

原始 observation 的 13–21、27–31，以及未列入白名单的前缀置零；不读取 seed、RNG、未来奖励/遭遇、第二个 Boss、未翻开的记忆牌或燃烧精英增益。事件名称/金额限事件界面；地图后缀、公开牌组/遗物/药水向量保留。候选描述的隐藏记忆牌标记沿用运行包编码器。

## 同一状态逐位检查

在模拟器与原版桥各导出一个 packet JSON，均须附 `bits` 和 `descriptors`。检查脚本对候选顺序、六组输入和每个候选的 11195 维特征比较 float32 的每一位，失败时输出首个差异坐标与值：

```bash
python distill2_parity.py --model /absolute/path/distill2_frozen.pt \
  --left simulator-state.json --right java-state.json
```

对训练加载路径的检查：

```bash
python distill2_parity.py --model /absolute/path/distill2_frozen.pt \
  --trajectory-dir /path/to/student/traces --student-replay \
  --teacher-module p300_play_v21 --limit 200 --output /path/to/checks
```

同一文件与自身比较只能验证工具，不能证明 Java 对齐。当前提供的两局 fixture 核验训练与推理；Java 侧逐位对齐由对接任务提供独立 packet 后核验。

## 模型状态与固定路径

云端生产管线输出：`~/sts/runs/distill2-v21-20260930/frozen/`。

本机镜像目标：`student/models/distill2_frozen.pt`。

文件在两轮 DAgger 重训结束后生成；`freeze.json` 保存 SHA-256 与 schema ID。训练测试用 smoke 模型不属于交付候选。模型文件冻结、开发评估通过、1024 最终验收通过是三个状态；本次管线不触碰锁定验收块。

接口测试权重：`models/distill2_smoke_interface_only.pt`。这是 10 局提取数据训练 1 个 epoch 的管线测试权重，供 Java 适配器检查加载、维度和动作映射；不是生产候选，不用于胜率判断或最终验收。`checks/packet-*.json` 是模拟器输出的公共状态示例。
