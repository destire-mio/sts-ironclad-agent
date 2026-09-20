"""Publish completed E121 admission separately from its pending checkpoint."""
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
assert proof['status'] == 'complete' and proof['source_refresh_permitted']
for name, expected in proof['hashes'].items(): assert sha(Q / name) == expected, name
route = proof['original_route']
checks = proof['turn_order_checks']
entry = f'''

## 140. E121：整局原版对照通过，允许登记新来源（2026-09-20）

预选开发种子 1138994370 在 E121 引擎、父网络和原搜索预算下从自然开局通关心脏，重复规划的动作前缀与终局指纹匹配，终局 HP {route['hp']}。{proof['fresh_outside_NN_choices_audited']} 次局外神经网络选择完成核验；原版 {route['commands']} 个命令、三钥匙、第三幕两个不同 Boss、第四幕矛盾与心脏、持久 RNG 和共同终局 12 路 RNG 对照通过。没有导入中途状态或重同步。

原版执行和记录重放分别完成 {checks['original']['checks']}／{checks['recorded']['checks']} 次新增比较，其中包含本轮回调能力的状态为 {checks['original']['order_bearing_checks']}／{checks['recorded']['order_bearing_checks']} 个。比较覆盖回合开始、抽牌后和回合结束三个修改的阶段，并保留逐枚炸弹检查；无相关回调的能力顺序不作为该阶段的行为差异。炸弹出现状态的计数为 {checks['original']['bomb_bearing_checks']}／{checks['recorded']['bomb_bearing_checks']}，炸弹混合状态的证据范围仍以 §139 的构造与控制记录为准。所属进程与独立原版实例完成清理。

完成门禁检查 279 项本地回归、47 项补丁重建检查、90 个源码摘要、E120 四组原版记录／七个快照后缀、E116 四组炸弹记录，以及整局来源和比较器身份。可变模拟器采用三份验证后的源码；父模型没有变化。完成证明 `{sha(Q / 'completion-verification.json')}`，引擎 `{proof['engine_sha256']}`，公开报告 `sim_patch/alignment/e121-power-order-report.json`。

允许在新目录登记 E121 来源，旧引擎结果不转为新标签；E117 停止，E118／E119 关闭。此路线是开发集成，不是模型学习收益或未见种子胜率；未见 1024 种子至少 512 次心脏通关的目标未完成。下一步恢复尚未执行的数据量对照：父网络固定，遗物与选牌两个决策入口共享同一训练方案，比较嵌套的少量／扩展家族数据。长任务检查间隔 20 分钟。
'''
ledger = W / '铁甲战士项目路线与RL实验.md'
assert '## 140. E121' not in ledger.read_text()
ledger.write_text(ledger.read_text() + entry)
archive = R / 'docs/ironclad-experiments.md'
header = '\n'.join(archive.read_text().splitlines()[:4]) + '\n'
archive.write_text(header + ledger.read_text())
alignment = A / '对齐报告.md'
assert '## 140. E121' not in alignment.read_text()
alignment.write_text(alignment.read_text() + entry)
english = ('**Current development (September 20): E121 repairs player turn power order and passes scoped original integration.** '
    '279 local checks, 47 clean patch-build checks and four recorded E120 sequences pass. '
    f'One preselected natural Heart route repeats at {route["hp"]} HP; {route["commands"]} original commands, all outside choices and twelve terminal RNG streams match. '
    'Live and recorded comparisons include the three repaired turn phases and Bomb instances. '
    'New source registration is permitted; E117 stays stopped and E118/E119 closed. '
    'This is development repair evidence; the 50% unseen-seed goal remains open. '
    '[Repair](sim_patch/alignment/e121-power-order-report.json), [current status](docs/ironclad-training-status.md).')
for relative in ('README.md', 'docs/ironclad-training-status.md'):
    path = R / relative; lines = path.read_text().splitlines()
    indexes = [i for i, line in enumerate(lines) if line.startswith('**Current development (September 20): E121')]
    assert len(indexes) == 1
    lines[indexes[0]] = english if relative == 'README.md' else english.replace('(sim_patch/', '(../sim_patch/').replace('(docs/ironclad-training-status.md)', '(ironclad-training-status.md)')
    path.write_text('\n'.join(lines) + '\n')
path = R / 'README.zh-CN.md'; lines = path.read_text().splitlines()
indexes = [i for i, line in enumerate(lines) if line.startswith('**2026-09-20 开发状态：E121')]
assert len(indexes) == 1
lines[indexes[0]] = ('**2026-09-20 开发状态：E121 修复能力顺序丢失，通过范围内整局原版对照。** '
    '279 项本地检查、47 项补丁重建检查、四组原版记录及一条预选自然心脏路线通过；局外选择和 12 路终局 RNG 匹配。'
    '允许登记新来源；E117 停止，E118／E119 关闭。修复证据不代表学习收益或未见种子胜率，50% 目标未完成。'
    '[修复报告](sim_patch/alignment/e121-power-order-report.json)、[当前状态](docs/ironclad-training-status.md)。')
path.write_text('\n'.join(lines) + '\n')
path = R / 'sim_patch/README.md'; text = path.read_text()
text = text.replace('### E121: player turn power order (integration pending)', '### E121: player turn power order')
text = text.replace('Full natural/original integration is registered but not admitted at this checkpoint. Keep training and source collection stopped until its completion gate passes.',
    'The registered natural/original Heart integration passed, including all outside choices, phase-specific order and twelve terminal RNG streams. Register a new source under E121; old E117 outcomes do not become new-engine labels.')
text += '\n[Completed E121 result](alignment/e121-power-order-report.json). The preparation link above is its historical pending checkpoint.\n'
path.write_text(text)
dest = R / 'docs/experiments/e121-repair-sources'
shutil.copyfile(__file__, dest / 'publish-completion.py')
assert archive.read_text() == header + ledger.read_text()
with (Q / 'completion-publication.json').open('x') as f:
    json.dump({'status': 'published_complete', 'section': 140,
        'completion_sha256': sha(Q / 'completion-verification.json'),
        'report_sha256': sha(R / 'sim_patch/alignment/e121-power-order-report.json'),
        'source_refresh_permitted': True, 'learned_or_unseen_claim': False}, f, indent=2); f.write('\n')
print({'section': 140, 'status': 'published_complete', 'route': route})
