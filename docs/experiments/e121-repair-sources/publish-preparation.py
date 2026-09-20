"""Record tested repair and pending integration without admitting training."""
from pathlib import Path
import hashlib
import json
import shutil

Q = Path(__file__).resolve().parent
A = Q.parents[1]
W = A.parent
R = W / 'sts-rl-agent-pr'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())
local = read(Q / 'local-verification.json')
assert local['status'] == 'passed' and local['full_ctest_cases'] == 279
registration = read(Q / 'integration-registration.json')
for path, expected in registration['hashes'].items(): assert sha(path) == expected, path
schedule = read(Q / 'observation-schedule.json')
assert schedule['interval_seconds'] == 1200
public = {'experiment': 'E121', 'status': 'local_passed_integration_pending',
    'engine_sha256': local['engine_sha256'], 'model_sha256': read(Q / 'candidate/identity.json')['model_sha256'],
    'local_verification': local,
    'patch_sha256': sha(R / 'sim_patch/e121_power_order.patch'),
    'integration_registration_sha256': sha(Q / 'integration-registration.json'),
    'integration_started_at': schedule['started_at'],
    'next_observation_at': schedule['next_observation_at'],
    'selected_development_seed': 1138994370, 'long_job_observation_interval_seconds': 1200,
    'source_refresh_permitted': False, 'optimizer_updates': 0, 'new_training_labels': 0,
    'limits': 'Local repair evidence; full natural/original integration has not been inspected or admitted at publication. The mutable simulator stays E116 until the completion gate passes. E117 stopped and E118/E119 closed. No unseen or learned success claim.'}
with (R / 'docs/experiments/e121-repair-preparation.json').open('x') as f:
    json.dump(public, f, indent=2); f.write('\n')
entry = f'''

## 139. E121：保存能力顺序的修复与本地验证（2026-09-20，整局验收待检查）

E120 的原版差异对应的修复采用“原版优先级 → 同级获得顺序”。叠加保留原位置，移除后重加排入新位置；每枚炸弹以战斗副本内的实例编号进入同一顺序。快照沿原版能力数组导入，状态文字和公开导出保留顺序，搜索分支按值复制。现有回合开始、抽牌后、回合结束三个能力遍历使用该顺序；遍历时复制顺序列表，避免同步移除能力跳过下一个回调。其他钩子阶段不在本轮修复范围。

15 项 C++ 行为检查从 11 失败、4 通过变为 15 通过，覆盖两个出牌顺序、遗物／能力缺席、叠加、移除与归零后重加、人工制品阻挡、分支与队列复制、状态指纹、缠绕的优先级以及炸弹混排。五项公开 Python 绑定检查通过。E120 四组原版记录的 11 个命令连续比对通过；七个导入后缀与复制对照共 38 次顺序比较通过。相同能力和数值的错误顺序被拒绝，并产生 4 张与 3 张剩余抽牌堆的差别。E116 四组炸弹原版记录的 23 个命令、15 个后缀和 110 次实例比较通过。主控制序列无中途重同步。

本地现有 263 项检查与新增 16 项 CTest 入口共 279 项通过；公开补丁重建的 90 个源文件匹配，47 项相关检查通过。本地 CMake 原来漏列 E94 终局检查，本轮补入原有入口并核对 263 个既有名称未丢失。构建中的命名冲突、缺失 JSON_INCLUDE、测试误用进程诊断计数的失败记录保留。初始“抽牌致死导致恶魔形态不加力量”的两个拟议用例被源码和旧版执行反驳：火焰吐息伤害排在恶魔形态后，因此不作为游戏缺陷或修复收益计数。

候选引擎 `{local['engine_sha256']}`，父模型 `{public['model_sha256']}`，补丁 `{public['patch_sha256']}`。预选开发种子 1138994370 的自然 NN／MCTS、胜局重规划、原版整局、逐枚炸弹与分阶段能力顺序、终局 12 路 RNG 验证于 {schedule['started_at']} 启动。观察间隔 1200 秒，下次检查 {schedule['next_observation_at']}；此记录不读取或宣告验收结果。全程对照的新增顺序判定限定三个修改的回调阶段，无相应回调的能力顺序不作为该阶段的行为差异。

完成门禁通过前，不采用到可变模拟器，不收集新训练标签。E117 停止，E118／E119 关闭；参数更新和未见种子验收为 0，50% 目标未完成。公开入口为 `sim_patch/e121_power_order.patch` 和 `docs/experiments/e121-repair-preparation.json`；下一步读取此次注册的整局结果，通过后运行 `finalize-repair.py`，失败则保留现场诊断，不更换种子。
'''
ledger = W / '铁甲战士项目路线与RL实验.md'
assert '## 139. E121' not in ledger.read_text()
ledger.write_text(ledger.read_text() + entry)
archive = R / 'docs/ironclad-experiments.md'
header = '\n'.join(archive.read_text().splitlines()[:4]) + '\n'
archive.write_text(header + ledger.read_text())
report = A / '对齐报告.md'; assert '## 139. E121' not in report.read_text()
report.write_text(report.read_text() + entry)
english = ('**Current development (September 20): E121 retains player power order; full-run admission is pending.** '
    'The E120 controlled mismatch is repaired: all four recorded original sequences match. '
    '279 local checks and 47 clean patch-build checks pass; snapshots and copies retain order. '
    'One preselected development route is registered for natural, original and RNG integration. '
    'Training and source collection wait for that gate. E117 stays stopped, E118/E119 closed; the 50% unseen goal remains open. '
    '[Preparation](docs/experiments/e121-repair-preparation.json), [current status](docs/ironclad-training-status.md).')
p = R / 'README.md'; lines = p.read_text().splitlines()
indexes = [i for i, line in enumerate(lines) if line.startswith('**Current development (September 20):')]
assert len(indexes) == 1; lines[indexes[0]] = english; p.write_text('\n'.join(lines) + '\n')
p = R / 'docs/ironclad-training-status.md'; lines = p.read_text().splitlines()
indexes = [i for i, line in enumerate(lines) if line.startswith('**E117 is stopped; E120')]
assert len(indexes) == 1
lines[indexes[0]] = english.replace('(docs/experiments/', '(experiments/').replace('(docs/ironclad-training-status.md)', '(ironclad-training-status.md)')
p.write_text('\n'.join(lines) + '\n')
p = R / 'README.zh-CN.md'; lines = p.read_text().splitlines()
indexes = [i for i, line in enumerate(lines) if line.startswith('**2026-09-20 开发状态：')]
assert len(indexes) == 1
lines[indexes[0]] = ('**2026-09-20 开发状态：E121 能力顺序修复通过本地验证，整局验收待检查。** '
    '279 项本地检查、47 项补丁重建检查及 E120 四组原版记录通过。预选开发种子的自然运行、原版和 RNG 对照启动，长任务每 20 分钟检查。'
    '门禁通过前保持训练与来源收集停止；E117 停止，E118／E119 关闭，50% 未见种子目标未完成。'
    '[修复准备](docs/experiments/e121-repair-preparation.json)、[当前状态](docs/ironclad-training-status.md)。')
p.write_text('\n'.join(lines) + '\n')
p = R / 'sim_patch/README.md'
p.write_text(p.read_text() + '''

### E121: player turn power order (integration pending)

Apply `e121_power_order.patch` after E116 and rebuild core, search and Python bindings together. Player state retains priority and stable acquisition order, including individual Bombs. Stacking keeps position; removal and reapplication update it. The existing start, post-draw and end-turn callback loops consume that order; snapshots, copies and `Player.power_order` preserve it.

279 local checks, 47 clean portable checks and four recorded E120 original sequences pass. Full natural/original integration is registered but not admitted at this checkpoint. Keep training and source collection stopped until its completion gate passes. Other hook phases remain outside this scoped repair.

[Manifest](alignment/e121-power-order-manifest.json), [preparation](../docs/experiments/e121-repair-preparation.json).
''')
dest = R / 'docs/experiments/e121-repair-sources'; dest.mkdir()
for name in ['prepare.py', 'prepare-portable.py', 'prepare-integration.py', 'compare-controls.py',
        'power_order.py', 'turn_extras.py', 'integrate.py', 'prepare-recorded.py',
        'audit-terminal-rng.py', 'finalize-repair.py', 'publish-preparation.py']:
    shutil.copyfile(Q / name, dest / name)
assert archive.read_text() == header + ledger.read_text()
with (Q / 'preparation-publication.json').open('x') as f:
    json.dump({'status': 'published_pending', 'section': 139,
        'preparation_report_sha256': sha(R / 'docs/experiments/e121-repair-preparation.json'),
        'source_files': {p.name: sha(p) for p in dest.iterdir()},
        'training_permitted': False, 'integration_result_observed': False}, f, indent=2); f.write('\n')
print({'section': 139, 'status': 'local_passed_integration_pending', 'next_observation_at': schedule['next_observation_at']})
