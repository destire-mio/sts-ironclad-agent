"""Publish E122 source launch and entry gates without reading partial outcomes."""
from pathlib import Path
import hashlib
import json
import shutil

N = Path(__file__).resolve().parent
R = N.parents[1]
W = R.parent
A = W / 'ironclad-alignment'
Q = A / 'evidence/e122-development-parity-20260920-01'
E = A / 'evidence/e121-power-order-repair-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
reg = read(N / 'execution-registration.json')
for path, expected in reg['hashes'].items(): assert sha(path) == expected, path
for path, expected in read(Q / 'registration.json')['harness_sha256'].items(): assert sha(path) == expected, path
launch = read(N / 'launch-verification.json')
assert launch['status'] == 'live_verified_at_launch' and launch['workers_configured'] == 8
assert read(E / 'completion-verification.json')['source_refresh_permitted']
identity = read(N / 'natural/identity.json')
assert identity == read(E / 'candidate/identity.json')
assert sha(N / 'seeds.json') == sha(N.parent / 'heart-e116-scale-source-refresh-20260920-01/seeds.json')
assert sha(N / 'family-groups.json') == sha(N.parent / 'heart-e116-scale-source-refresh-20260920-01/family-groups.json')
turn = read(N / 'turn-entry-verification.json')
rng = read(N / 'terminal-rng-entry-verification.json')
assert len(turn['negative_cases']) == 22 and len(rng['negative_cases']) == 15
public = {'experiment': 'E122', 'status': 'source_launched', 'launch_verified_at': launch['at'],
    'identity': identity, 'families': read(N / 'protocol.json')['counts'], 'workers': 8,
    'source_registration_sha256': sha(N / 'registration.json'),
    'source_manifest_sha256': sha(N / 'natural/manifest.json'),
    'original_registration_sha256': sha(Q / 'registration.json'),
    'execution_registration_sha256': sha(N / 'execution-registration.json'),
    'repair_completion_sha256': sha(E / 'completion-verification.json'),
    'role_files_byte_identical': True, 'source_controller_pid_at_launch': launch['process']['pid'],
    'source_process_group_at_launch': launch['process']['process_group'],
    'owned_descendants_at_launch': len(launch['matched_processes']) - 1,
    'long_job_observation_seconds': 1200, 'next_observation_at': launch['next_observation_at'],
    'entry_checks': {'runtime_modules': 10, 'native_bomb_states': read(N / 'bomb-entry-verification.json')['original_control_states'],
        'wrong_bomb_instances_and_countdown_rejected': True, 'native_order_states': turn['original_control_states'],
        'wrong_order_same_amount_rejected': turn['wrong_order_same_amount_rejected'],
        'turn_proof_negative_cases': len(turn['negative_cases']), 'terminal_rng_negative_cases': len(rng['negative_cases']),
        'known_natural_actions_replayed': rng['known_natural_replay']['natural_actions'],
        'incomplete_source_rejected_before_original_launch': True,
        'owned_process_controls_reused': ['normal', 'fault', 'timeout', 'wrapper_SIGTERM']},
    'original_gate_launched': False, 'labels_collected': 0, 'optimizer_updates': 0,
    'limits': 'Launch checkpoint, not a completed source result or win rate. All 6144 sources and winner replans plus all 512 development audits and every development-winning original route must pass before continuation labels. Native admission includes Bomb instances, turn-phase order and twelve terminal RNG streams. E117 stays stopped, E118/E119 closed. The final 1024 unseen families remain separate.'}
path = R / 'docs/experiments/e122-source-launch.json'
with path.open('x') as f: json.dump(public, f, indent=2); f.write('\n')
entry = f'''

## 141. E122：E121 引擎的新来源采样启动（2026-09-20）

E121 完成门禁通过后登记新来源，保持 6144 个种子的角色分组与家族分组文件不变：fit 4608、label_holdout 1024、train_development 512。父模型 `{identity['model_sha256']}`、MCTS 8000／Boss ×3／单回合 cap256 和时间输入规则不变，引擎采用 `{identity['engine_sha256']}`。八个单线程工作进程从自然开局生成来源，保留早败、缺少决策节点和故障；旧 E117 结果不复用为新引擎标签。

启动前核对十个运行时模块、来源身份、角色互斥和不完整开发来源的拒绝行为。炸弹控制状态 15 个与两类损坏检查通过；能力顺序控制状态 11 个、相同数值错误顺序检查及 22 个来源证明损坏检查通过；终局随机数助手在 E121 的 965 个自然动作记录和 15 个损坏对照上通过。执行器沿用通过正常／故障／超时／SIGTERM 四类进程隔离检查的实现；原版来源不完整时在实例启动前拒绝。

采样控制器于 {launch['at']} 被操作系统确认为运行，PID {launch['process']['pid']}、进程组 {launch['process']['process_group']}，所属子进程 {len(launch['matched_processes']) - 1} 个，其中配置八个工作进程。长任务观察间隔 1200 秒，下次检查 {launch['next_observation_at']}；此发布不读取部分终局结果，也不报告阶段胜率。

开发集 512 个来源齐备后启动一条原版 JVM 对照链；所有开发成功路线都必须完成原版、记录重放、逐枚炸弹、三个回调阶段的能力顺序和 12 路终局随机数检查。全部 6144 个来源、终局／RNG／局外选择核验和胜局重规划完成后，才允许后续续局标签采集。来源比较证明和后续训练比较证明将使用同一顺序条件，缺失顺序结果不能通过门禁。

执行登记 SHA `{sha(N / 'execution-registration.json')}`，公开启动报告 `docs/experiments/e122-source-launch.json`。E117 停止，E118／E119 关闭；新训练标签、参数更新和未见种子验收为 0。数据量对照的假设仍未验证，后继 E123／E124 的准备将在新目录进行；未见种子 50% 目标未完成。
'''
ledger = W / '铁甲战士项目路线与RL实验.md'
assert '## 141. E122' not in ledger.read_text(); ledger.write_text(ledger.read_text() + entry)
archive = R / 'docs/ironclad-experiments.md'
header = '\n'.join(archive.read_text().splitlines()[:4]) + '\n'
archive.write_text(header + ledger.read_text())
alignment = A / '对齐报告.md'; assert '## 141. E122' not in alignment.read_text()
alignment.write_text(alignment.read_text() + entry)
for relative in ('README.md', 'docs/ironclad-training-status.md'):
    p = R / relative; lines = p.read_text().splitlines()
    indexes = [i for i, line in enumerate(lines) if line.startswith('**Current development (September 20): E121')]
    assert len(indexes) == 1
    i = indexes[0]
    lines[i] = lines[i].replace('New source registration is permitted;',
        'E122 has launched the unchanged 6,144-family source study with eight workers and 20-minute observations;')
    link = 'docs/experiments/e122-source-launch.json' if relative == 'README.md' else 'experiments/e122-source-launch.json'
    lines[i] += f' [Source launch]({link}).'
    p.write_text('\n'.join(lines) + '\n')
p = R / 'README.zh-CN.md'; text = p.read_text()
text = text.replace('允许登记新来源；E117 停止，E118／E119 关闭。',
    'E122 的 6144 局新来源采样启动，八进程，20 分钟检查间隔；E117 停止，E118／E119 关闭。')
p.write_text(text)
dest = R / 'docs/experiments/e122-source-sources'; dest.mkdir()
paths = [N.parent / 'prepare-e122-20260920-01.py', N.parent / 'prepare-e122-execution-20260920-01.py']
paths += [N / name for name in ('prepare_source.py', 'check-entry.py', 'check-bomb-entry.py',
    'check-terminal-entry.py', 'check-turn-entry.py', 'run_job.py', 'observe.py', 'publish-launch.py')]
paths += [Q / name for name in ('cohort.py', 'power_order.py', 'turn_extras.py', 'bomb_instances.py', 'terminal_rng.py')]
for source in paths: shutil.copyfile(source, dest / source.name)
assert archive.read_text() == header + ledger.read_text()
with (N / 'launch-publication-verification.json').open('x') as f:
    json.dump({'status': 'published', 'report_sha256': sha(path),
        'sources': {p.name: sha(p) for p in dest.iterdir()}, 'partial_outcomes_read': False}, f, indent=2); f.write('\n')
print({'section': 141, 'source_report': str(path), 'published_sources': len(paths)})
