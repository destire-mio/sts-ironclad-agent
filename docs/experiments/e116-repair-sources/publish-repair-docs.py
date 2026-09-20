"""Publish the completed E116 evidence, excluding models and raw game records."""
from pathlib import Path
import hashlib
import json
import shutil

Q = Path(__file__).resolve().parent
A = Q.parents[1]
W = A.parent
R = W / 'sts-rl-agent-pr'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
proof = json.loads((Q / 'completion-verification.json').read_text())
assert proof['status'] == 'complete'
for name, expected in proof['hashes'].items(): assert sha(Q / name) == expected, name
route = proof['original_route']
entry = f'''

## 131. E116：逐枚炸弹的状态与结算修复（2026-09-20，范围内验证完成）

每枚炸弹保留倒计时和伤害；到期时排入独立伤害动作。倒计时减少通过队列执行，使用战斗副本内的实例编号，复制后的搜索分支不共享可变对象。状态导入、导出与文字指纹保留实例；旧的三个回合伤害总量接口从实例计算，不再作为第二份可变状态。缺失或非正倒计时的快照被拒绝；全体敌人死亡后不推进炸弹。

11 项 C++ 检查从七失败、四通过变为全部通过，覆盖双枚／升级混合、虚无与格挡、错开到期、高总伤害、相同总量不同实例数、复制及待执行队列。四个公开 Python 绑定用例覆盖导入后的独立伤害、错开倒计时、分支隔离及无效状态拒绝；它们在旧引擎失败。最终 263 项 CTest 通过；补丁重建的 90 个源文件匹配，含 E110／E111 的 31 项相关检查通过。

E115 四组原版序列共 23 个命令从各初始夹具连续重放，两个原差异与两个对照全部匹配。增加独立逐枚检查，15 个原版中途状态分别导入并复制后续执行，两种构建各进行 110 次实例比较；主序列不重同步，单独的快照测试有明确边界。五枚 40 与四枚 50 的总伤害相同，但状态与虚无伤害不同，错误合并被拒绝。

预先选定种子 1138994370 的父网络／MCTS 从自然开局运行并重复规划，心脏终局 HP {route['hp']}；{proof['fresh_outside_NN_choices_audited']} 次局外选择、原版 {route['commands']} 个命令、三钥匙／双 Boss／第四幕、持久 RNG 和共同终局 12 路 RNG 通过核验。原版与记录重放增加逐枚炸弹检查；所有所属进程清理完成。该种子用于修复集成，不能作为未见种子胜率证据。

初次在外层仓库子目录调用 git apply 跳过补丁文件，90 文件摘要核验拒绝该结果；后续构建的七项预期失败保留。在新目录用明确工作目录应用同一补丁，源码核验后构建通过，未改变用例预期。修复未覆盖不同能力种类之间的回调相对顺序；mapRng 内部状态没有模拟器导出，地图内容由整局比较器核对。

引擎 SHA `{proof['engine_sha256']}`，补丁 SHA `{proof['patch_sha256']}`，完成证明 SHA `{sha(Q / 'completion-verification.json')}`。公开补丁 `sim_patch/e116_bomb_instances.patch`，报告 `sim_patch/alignment/e116-bomb-instance-report.json`。允许登记新引擎来源；E112 不重启，E113／E114 保持关闭。新训练标签、参数更新、未见种子验收均为 0；50% 目标未完成。长任务观察间隔为 20 分钟。
'''
ledger = W / '铁甲战士项目路线与RL实验.md'
assert '## 131. E116' not in ledger.read_text()
ledger.write_text(ledger.read_text() + entry)
archive = R / 'docs/ironclad-experiments.md'
header = '\n'.join(archive.read_text().splitlines()[:4]) + '\n'
archive.write_text(header + ledger.read_text())
alignment = A / '对齐报告.md'
assert '## 131. E116' not in alignment.read_text()
alignment.write_text(alignment.read_text() + entry)

english = ('**Current development (September 20): E116 repairs individual Bomb state and damage.** '
    f'263 regression cases, 31 portable checks, four original control sequences and one preselected natural Heart route pass. '
    f'The route repeats at {route["hp"]} HP; {route["commands"]} original commands, all outside choices and twelve terminal RNG streams match. '
    'This is scoped repair evidence, not a learned or unseen-win result. New source registration is permitted; E112 stays stopped and E113/E114 stay closed. '
    'The 50% goal remains open. Long-job observations use 20-minute intervals. '
    '[Repair](sim_patch/alignment/e116-bomb-instance-report.json), [current status](docs/ironclad-training-status.md).')
p = R / 'README.md'; lines = p.read_text().splitlines()
indexes = [i for i, line in enumerate(lines) if line.startswith('**Current development (September 20): E115')]
assert len(indexes) == 1; lines[indexes[0]] = english; p.write_text('\n'.join(lines) + '\n')
p = R / 'README.zh-CN.md'; content = p.read_text()
anchor = '当前 A20 心脏策略采用 **E60（2026-09-18）**。'
assert anchor in content
note = ('**2026-09-20 开发状态：E116 修复炸弹实例丢失。** 263 项回归、31 项补丁重建检查、四组原版控制序列及一条预选自然心脏路线通过；'
        '整局原版动作、局外选择与 12 路终局 RNG 匹配。E112 停止，E113／E114 关闭，允许登记新来源。'
        '这是规则修复证据，50% 未见种子目标未完成；长任务每 20 分钟检查。'
        '[修复报告](sim_patch/alignment/e116-bomb-instance-report.json)、[当前状态](docs/ironclad-training-status.md)。\n\n')
p.write_text(content.replace(anchor, note + 'E60（2026-09-18）的历史模拟器结果：', 1))
p = R / 'docs/ironclad-training-status.md'; lines = p.read_text().splitlines()
indexes = [i for i, line in enumerate(lines) if line.startswith('**E115 confirms a Bomb')]
assert len(indexes) == 1
lines[indexes[0]] = english.replace('(sim_patch/', '(../sim_patch/').replace('(docs/ironclad-training-status.md)', '(ironclad-training-status.md)')
p.write_text('\n'.join(lines) + '\n')
instructions = '''

### E116: independent Bomb powers

Apply `e116_bomb_instances.patch` after E111, then rebuild core, search and Python bindings together. Bombs retain separate countdowns and damage actions; queued reductions address branch-local instances. `Player.bombs` remains a derived three-total view, while `Player.bomb_instances` exposes every `(turns, damage)` pair. Missing or nonpositive imported countdowns reject the snapshot.

263 CTest cases and 31 clean portable cases pass, including public import/copy regressions. Four recorded original controls and one preselected full natural route pass with additive per-instance power checks and twelve terminal RNG streams. The failed initial patch-application attempt is preserved. This admits a newly registered source refresh, not old E112 labels, model improvement or exhaustive parity. Relative ordering among different power types remains outside the scoped repair.

[Manifest](alignment/e116-bomb-instance-manifest.json), [completed result](alignment/e116-bomb-instance-report.json).
'''
p = R / 'sim_patch/README.md'; assert '### E116:' not in p.read_text(); p.write_text(p.read_text() + instructions)
source_dir = R / 'docs/experiments/e116-repair-sources'; source_dir.mkdir()
for name in ('compare-controls.py', 'bomb_extras.py', 'prepare-candidate.py', 'integrate.py',
             'finalize-repair.py', 'prepare-recorded.py', 'audit-terminal-rng.py', 'publish-repair-docs.py'):
    shutil.copyfile(Q / name, source_dir / name)
assert archive.read_text() == header + ledger.read_text()
with (Q / 'documentation-publication.json').open('x') as f:
    json.dump({'status': 'verified', 'repair_proof_sha256': sha(Q / 'completion-verification.json'),
               'ledger_and_archive_equal': True,
               'source_files': {p.name: sha(p) for p in sorted(source_dir.iterdir())}}, f, indent=2); f.write('\n')
print({'status': 'published', 'section': 131, 'source_files': len(list(source_dir.iterdir()))})
