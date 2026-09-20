"""Preserve the pending draw-order hypothesis without claiming native confirmation."""
from pathlib import Path
import ast
import hashlib
import json
import shutil

Q = Path(__file__).resolve().parent
A = Q.parents[1]
W = A.parent
R = W / 'sts-rl-agent-pr'
D = R / 'docs/experiments'
PUBLIC = D / 'e125-draw-order-sources'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
source, run, native = [read(Q / name) for name in ('source-plan.json', 'source-run.json', 'native-plan.json')]
assert run['exit_code'] == 0 and run['plan_sha256'] == sha(Q / 'source-plan.json')
assert sha(Q / 'draw-order.cpp') == source['code_sha256']
assert sha(Q / 'draw-order') == source['binary_sha256']
for path, expected in source['source_hashes'].items():
    assert sha(path) == expected, path
for path, expected in native['harness_sha256'].items():
    assert sha(path) == expected, path
assert native['source_plan_sha256'] == sha(Q / 'source-plan.json')
assert native['source_diagnostic_sha256'] == sha(Q / 'source-run.json')
assert not (Q / 'original-controls').exists()
rows = json.loads(run['stdout'])
assert len(rows) == 4 and [r['simulator'] != r['source_ordered_reference'] for r in rows] == [True, False, False, False]
PUBLIC.mkdir()
for name in ('draw-order.cpp', 'original-diagnostic.py', 'compare-original.py', 'publish-preparation.py'):
    if name.endswith('.py'):
        ast.parse((Q / name).read_text())
    shutil.copyfile(Q / name, PUBLIC / name)
    assert sha(Q / name) == sha(PUBLIC / name)
(PUBLIC / 'README.md').write_text(
    'E125 own-code controls for one pending draw-order hypothesis under the frozen E121 core. '
    'The C++ reference follows local original source order; it is not an original-game execution. '
    'Four native sequences are preregistered locally and wait for the existing E122 native slot. '
    'The native controller checks owned-process exit, native cleanup and no live game JVM before preparing its instance. '
    'No game JARs, model weights or raw game traces are included. Scripts depend on the local registered evidence layout.\n')
report = {'experiment': 'E125', 'status': 'source_difference_pending_original_validation',
    'engine_sha256': source['engine_sha256'], 'hypothesis': source['hypothesis'],
    'source_plan_sha256': sha(Q / 'source-plan.json'), 'source_run_sha256': sha(Q / 'source-run.json'),
    'native_plan_sha256': sha(Q / 'native-plan.json'), 'source_controls': rows,
    'native_cases_registered': [s['name'] for s in native['specs']],
    'native_commands_registered': sum(len(s['play_order']) for s in native['specs']),
    'native_slot_rule': native['slot'], 'new_original_instances': 0,
    'new_mcts_calls': 0, 'optimizer_updates': 0, 'engine_modified': False,
    'limits': 'One source-derived C++ discrepancy and three matching controls. No original-game confirmation, natural-cohort mismatch or training gain. E122 has not been stopped by this hypothesis. Native results must determine whether a repair is warranted.'}
with (D / 'e125-draw-order-preparation.json').open('x') as stream:
    json.dump(report, stream, indent=2)
    stream.write('\n')
section = '''

## 144. E125：抽牌能力顺序的待验证差异（2026-09-20）

检查 E121 未修改的抽牌回调发现，原版 AbstractPlayer.draw 按能力获得顺序遍历 onCardDraw，进化和火焰吐息均为默认优先级 5；冻结模拟器 CardManager::draw 固定先排进化抽牌、后排火焰吐息伤害。原版胜利清理会删除待执行抽牌。因此“先吐息、后进化，抽到伤口触发最后一击”可能阻止进化的抽牌与洗牌；反向顺序允许抽牌完成。

冻结 E121 核心的四组 C++ 控制中，目标组模拟器多消耗一次洗牌 RNG，并把日晷计数从 2 变成 0；按原版源码顺序排列相同动作的对照不洗牌，日晷保留 2。两个执行都赢得战斗，但随机数和遗物计数会带入后续战斗。反向获得顺序、非致死伤害和不带进化三组控制匹配。这是模拟器与源码推导的对照，尚不是原版执行证据。

原版验证登记四组、11 个真实出牌命令，每组仅设置一次初始夹具，通过实际打出能力获得顺序，不导入能力或中途同步。胜利后仍检查洗牌 RNG 内部状态和日晷；奖励生成使用的随机数不与尚未退出的 BattleContext 混比。原版控制须等待 E122 所属进程退出、原版实例清理完成且没有运行中的原版 JVM。当前没有启动该控制，也没有据此中断 E122 或修改引擎。

公开准备报告 `docs/experiments/e125-draw-order-preparation.json`，自有诊断代码 `e125-draw-order-sources/`。后续以实际原版结果接受或反驳假设；若确认影响训练，则修复后重新登记来源，不能把旧引擎标签当成新引擎数据。
'''
ledger = W / '铁甲战士项目路线与RL实验.md'
old = ledger.read_text()
assert '## 144.' not in old
ledger.write_text(old + section)
public_ledger = R / 'docs/ironclad-experiments.md'
header = ''.join(public_ledger.read_text().splitlines(keepends=True)[:4])
public_ledger.write_text(header + ledger.read_text())
alignment = A / '对齐报告.md'
old = alignment.read_text()
assert '## 144.' not in old
alignment.write_text(old + section)
with (Q / 'preparation-publication-verification.json').open('x') as stream:
    json.dump({'status': 'verified', 'public_hashes': {
        str(p.relative_to(R)): sha(p) for p in [*(p for p in PUBLIC.iterdir() if p.is_file()), D / 'e125-draw-order-preparation.json']},
        'ledger_section': 144, 'new_original_instances': 0, 'live_E122_outcomes_read': False}, stream, indent=2)
    stream.write('\n')
print({'status': 'verified', 'native_validation_pending': True, 'ledger_section': 144})
