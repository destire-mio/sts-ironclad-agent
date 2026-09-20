"""Publish E117 registration and completed entry checks; never read live source outcomes."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil

N = Path(__file__).resolve().parent
R = N.parents[1]
W = R.parent
A = W / 'ironclad-alignment'
Q = A / 'evidence/e117-development-parity-20260920-01'
E = A / 'evidence/e116-bomb-instance-repair-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())
def write(p, value):
    with p.open('x') as f: json.dump(value, f, indent=2); f.write('\n')

for p, expected in read(N / 'execution-registration.json')['hashes'].items(): assert sha(p) == expected, p
for p, expected in read(Q / 'registration.json')['harness_sha256'].items(): assert sha(p) == expected, p
for name, expected in read(N / 'natural/manifest.json')['frozen_files'].items(): assert sha(N / 'natural' / name) == expected
assert read(N / 'source-preparation-verification.json')['status'] == 'complete'
assert read(N / 'runtime-entry-verification.json')['status'] == 'complete'
assert read(N / 'original-entry-verification.json')['incomplete_source_rejected']
assert read(N / 'wrapper-entry-verification.json')['status'] == 'passed'
assert read(N / 'bomb-entry-verification.json')['same_total_wrong_instances_rejected']
assert read(N / 'terminal-rng-entry-verification.json')['status'] == 'passed'
assert read(E / 'completion-verification.json')['source_refresh_permitted']
launch = read(N / 'source-job/pipeline-process.json')
assert launch['registration_sha256'] == sha(N / 'execution-registration.json')
assert launch['command'][1] == str(N / 'natural/run_refresh.py')
report = {'experiment': 'E117', 'status': 'source_launched_entry_verified',
    'published_at': datetime.now(timezone.utc).isoformat(),
    'protocol': read(N / 'protocol.json'), 'launch_record': launch,
    'source_registration_sha256': sha(N / 'registration.json'),
    'source_manifest_sha256': sha(N / 'natural/manifest.json'),
    'original_registration_sha256': sha(Q / 'registration.json'),
    'execution_registration_sha256': sha(N / 'execution-registration.json'),
    'entry': {'runtime_modules': len(read(N / 'runtime-entry-verification.json')['modules']),
              'incomplete_source_rejected': True, 'incomplete_original_wrapper_rejected': True,
              'original_bomb_states': read(N / 'bomb-entry-verification.json')['original_control_states'],
              'same_total_wrong_instances_rejected': True, 'wrong_countdown_rejected': True,
              'terminal_rng_negative_controls': len(read(N / 'terminal-rng-entry-verification.json')['negative_cases']),
              'known_terminal_actions_replayed': 965},
    'optimizer_updates': 0, 'new_random_seed_draws': 0,
    'limits': 'Registration, entry checks and initial launch record only. Live source outcomes are not inspected by this publisher. All6144 sources and all512 development-original gates remain outstanding before labels and fits. No unseen acceptance or learned improvement.'}
write(R / 'docs/experiments/e117-source-refresh-protocol.json', report)
destination = R / 'docs/experiments/e117-preparation-sources'; destination.mkdir()
for name in ('prepare_source.py', 'check-entry.py', 'check-bomb-entry.py', 'check-terminal-entry.py',
             'run_job.py', 'observe.py', 'preparation-source.py', 'publish-preparation.py'):
    shutil.copyfile(N / name, destination / name)
for name in ('cohort.py', 'bomb_extras.py', 'bomb_instances.py', 'terminal_rng.py'):
    shutil.copyfile(Q / name, destination / name)
(destination / 'README.md').write_text('These own-code snapshots preserve local E117 registration and execution gates. They require the documented evidence layout, locally owned game installation, raw records and frozen runtime. They are not standalone public runners. No game JAR, checkpoint or raw trace is included.\n')
entry = f'''

## 132. E117：用逐枚炸弹修复后的引擎刷新来源（2026-09-20，采样启动）

E116 完成证明允许新来源登记；使用引擎 `{report['protocol']['scope']['engine_sha256']}`，父网络与 Python 执行器保持原字节。6,144 个种子及分组与 E112 相同：4,608 拟合、1,024 标签留出、512 开发，嵌套小组仍为 1,536。没有新抽验收种子。八个单线程工人、MCTS 8,000／Boss 三倍、单局／进程 300／360 秒、全来源与胜局重规划 10,800 秒保持一致；所属进程外层限额 11,100 秒。

十个实际运行模块路径与摘要通过核对。原版门槛在 512 个开发来源缺失时拒绝创建实例，包装程序同样拒绝；源采样入口通过。15 个现有原版炸弹状态匹配逐枚检查，五枚 40 与四枚 50 的总量相同对照证明旧聚合检查放过差异、新检查拒绝差异；错误倒计时也被拒绝。终局帮助脚本与 E112 相同，在 E116 已完成的自然路线重放 965 动作、12 路 RNG 匹配，15 个流状态／流集合损坏用例被拒绝。上述准备没有新 MCTS、原版实例或优化器更新。

原版门槛要求全部开发胜局新原版整局、追加持久 RNG、共同终局 12 路 RNG，并在新原版和记录重放中增加逐枚炸弹比较。每条证明绑定引擎、帮助脚本、轨迹与 RPC 摘要；旧原版比较器保留。来源和原版进程复用 E113 的已测试进程组清理函数，增加本轮准入与隔离 JVM 退出清理。

来源于 `{launch['started_at']}` 启动，后续按 20 分钟观察。来源登记 SHA `{report['source_registration_sha256']}`，原版登记 SHA `{report['original_registration_sha256']}`，执行登记 SHA `{report['execution_registration_sha256']}`。公开报告 `docs/experiments/e117-source-refresh-protocol.json`，自有准备／执行代码 `docs/experiments/e117-preparation-sources/`。全来源、胜局重规划和开发原版门槛尚未完成；没有新反事实标签或模型。E112／E113／E114 保持关闭，数据规模假设与 50% 未见种子目标未验收。
'''
ledger = W / '铁甲战士项目路线与RL实验.md'; assert '## 132. E117' not in ledger.read_text()
ledger.write_text(ledger.read_text() + entry)
archive = R / 'docs/ironclad-experiments.md'
header = '\n'.join(archive.read_text().splitlines()[:4]) + '\n'
archive.write_text(header + ledger.read_text())
status = R / 'docs/ironclad-training-status.md'
content = status.read_text()
marker = '**Current development (September 20): E116'
position = content.index(marker)
addition = ('**E117 source sampling is launched under the E116 Bomb repair.** Preserve the same 6,144 seed families, parent model, search budget and eight-worker configuration. '
    'All source/winner replay gates and all development-winner original routes are required before continuation labels. Original comparisons include individual Bomb state and twelve terminal RNG streams. '
    'The entry checks pass; this launch record contains no new model or source win-rate result. Observe long jobs every 20 minutes. '
    '[Registered protocol](experiments/e117-source-refresh-protocol.json).\n\n')
status.write_text(content[:position] + addition + content[position:])
write(N / 'publication-verification.json', {'status': 'verified',
    'report_sha256': sha(R / 'docs/experiments/e117-source-refresh-protocol.json'),
    'source_files': {p.name: sha(p) for p in sorted(destination.iterdir())},
    'ledger_and_archive_equal': archive.read_text() == header + ledger.read_text()})
print({'status': 'published', 'source_started_at': launch['started_at'], 'source_process_group': launch['process_group'],
       'next_observation_at': read(N / 'observation-schedule.json')['next_observation_at']})
