"""Record the completed observation and prepared successors without repolling jobs."""
from pathlib import Path
import hashlib
import json
import shutil

N = Path(__file__).resolve().parent
R = N.parents[1]
W = R.parent
A = W / 'ironclad-alignment'
D = R / 'docs/experiments'
T = N.parent / 'heart-e121-scale-training-20260920-01'
read = lambda p: json.loads(Path(p).read_text())
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
for name in ('preparation-publication-verification.json', 'execution-publication-verification.json'):
    value = read(T / name)
    assert value['status'] == 'verified'
    for path, digest in value['public_hashes'].items():
        assert sha(R / path) == digest, path
schedule = read(N / 'observation-schedule.json')
observation_path = Path(schedule['last_observation'])
observation = read(observation_path)
assert observation['observed_at'] == '2026-09-20T10:30:19.848055+00:00'
assert observation['source_files'] == 788
launch = read(N / 'original-launch-verification.json')
assert launch['status'] == 'original_controller_live'
report = {'experiment': 'E122', 'status': 'source_running_original_started',
    'observed_at': observation['observed_at'], 'source_files_saved': 788, 'registered_total': 6144,
    'source_controller_live': observation['processes']['source']['live'],
    'source_status': observation['source_status'], 'source_observation_sha256': sha(observation_path),
    'all_development_files_present_at_original_admission': 512,
    'original_started_at': launch['process']['started_at'], 'original_controller_live_at_launch': True,
    'original_launch_verification_sha256': sha(N / 'original-launch-verification.json'),
    'observer_interval_seconds': 1200, 'next_observation_at': schedule['next_observation_at'],
    'original_outcomes_inspected': False, 'new_continuation_labels': 0, 'optimizer_updates': 0,
    'limits': 'First source observation and original launch. Saved files are not full-source admission; no partial win rate, new trained candidate or unseen acceptance.'}
with (D / 'e122-first-observation.json').open('x') as stream:
    json.dump(report, stream, indent=2)
    stream.write('\n')
section = '''

## 142. E123／E124：数据量对照准备完成（2026-09-20）

在 E121 引擎与 E122 来源上接续尚未执行的数据量假设：少量组 1536 个 fit 家族，扩展组嵌套 4608 个 fit 家族，共用 1024 个标签留出家族和 512 个开发家族。两组使用父网络 192 维表示，学习第一幕 Boss 遗物和受限第二幕选牌的两个线性读出；每组固定 1000 次参数更新、学习率 0.03、L2 0.001。范围、步数、早败和缺失节点处理、家族分组与预算沿用原登记条件。

15 份采集模块逐字节保持，16 份脚本按记录迁移。来源入口与候选入口要求同一能力顺序证明，并保留逐枚炸弹、12 路终局 RNG、所有开发成功路线与来源完整性检查。54 个损坏证明、两种缺失顺序证明及 8 个嵌套脚本摘要损坏被拒绝。零增量模型的实际遗物／选牌调用、203 次局外选择、965 个自然动作记录、15 个炸弹原版控制状态与 11 个能力顺序控制状态通过。已知整局的炸弹出现计数为 0，顺序能力出现计数为 403；炸弹正例来自控制状态。这些是软件与已知记录检查，不是训练收益。

采集器在新目录通过正常、故障、超时、SIGTERM 四类清理检查，对照进程存活。训练包装器复用相同进程所有权函数，真实输入缺失时在输出和子进程创建前拒绝。18 小时是调度总期限，不是独立操作系统看门狗。准备时一次错误相对路径在读取首个模板失败，未创建执行器或启动子进程；记录保留，修正根目录后通过。旧 E117／E118／E119 的停止和关闭状态保持。

E123 等待 E122 全部 6144 来源、胜局重规划、512 个开发整局核验和全部开发胜局原版对照；E124 等待续局标签与独立核验完成。两个模型冻结后读取共同留出集，相对父策略净增至少 20／1024 且配对 p<0.05 才进入自然开发集；自然开发集要求净增至少 10／512、p<0.05、零故障与全部成功路线原版核验。扩展数据有效的结论要求扩展组相对少量组另行通过留出条件。最终未见 1024 种子的 50% 目标独立。

公开报告为 `docs/experiments/e123-label-preparation.json`、`e124-training-preparation.json`、`e124-training-execution.json`，自有代码位于 `e123-e124-prepared-sources/` 与 `e124-execution-sources/`。当前续局标签、参数更新、候选自然评估与未见种子验收均为 0。


## 143. E122：首个 20 分钟检查与原版对照启动（2026-09-20）

2026-09-20T10:30:19.848055+00:00 的检查记录 788／6144 个来源文件，控制器 PID 54754 的系统命令匹配，八个采样进程运行。内部状态文件记录 780 个完成项，反映写入时刻不同；文件计数不是全来源完成证明，不据此报告部分胜率。

随后开发组 512 个文件齐备，原版启动门禁通过；启动前系统没有原版 JVM。原版控制器 PID 66574 于 2026-09-20T10:31:04.211235+00:00 启动并完成系统读回，先核对 512 条来源，再逐条运行成功路线。原版结果未读取。下一次采样与原版合并观察为 2026-09-20T10:51:04.211235+00:00，即北京时间 18:51，间隔 1200 秒。

公开阶段报告 `docs/experiments/e122-first-observation.json`。此阶段没有续局标签、参数更新或未见种子验收。
'''
ledger = W / '铁甲战士项目路线与RL实验.md'
old = ledger.read_text()
assert '## 142.' not in old
ledger.write_text(old + section)
public_ledger = R / 'docs/ironclad-experiments.md'
header = ''.join(public_ledger.read_text().splitlines(keepends=True)[:4])
public_ledger.write_text(header + ledger.read_text())
alignment = A / '对齐报告.md'
old = alignment.read_text()
assert '## 142.' not in old
alignment.write_text(old + section)
status = R / 'docs/ironclad-training-status.md'
text = status.read_text()
start = text.index('**E119 has a prepared single-run execution wrapper.**')
end = text.index('\n\n', start)
text = text[:start] + (
    '**E123/E124 preparation is complete under E121.** The unchanged 1536-versus-4608 family study couples first Boss relic choice with scoped Act 2 card choice. Source and candidate admission share ordered turn-power, per-instance Bomb and twelve-stream terminal RNG checks. Actual incomplete inputs reject before outputs. No labels or optimizer updates have run. E122 saved 788/6144 source files at its first 20-minute observation, then launched the 512-development original gate. The next observation is 18:51 Shanghai. [Preparation](experiments/e124-training-preparation.json), [execution](experiments/e124-training-execution.json), [source checkpoint](experiments/e122-first-observation.json).'
) + text[end:]
status.write_text(text)
public_source = D / 'e122-first-observation-sources'
public_source.mkdir()
shutil.copyfile(__file__, public_source / 'publish-stage.py')
with (N / 'stage-publication-verification.json').open('x') as stream:
    json.dump({'status': 'verified', 'public_report_sha256': sha(D / 'e122-first-observation.json'),
        'ledger_sections': [142, 143], 'live_job_repolls': 0, 'raw_private_artifacts_published': False}, stream, indent=2)
    stream.write('\n')
print({'status': 'verified', 'ledger_sections': [142, 143], 'live_job_repolls': 0})
