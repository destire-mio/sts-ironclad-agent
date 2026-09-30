from pathlib import Path
import json
r=Path(__file__).resolve().parents[1];e=r/'evidence';linux=e/'linux-final';read=lambda p:json.loads(p.read_text())
mac=read(e/'fixed-summary-mac.json');lin=read(linux/'fixed-summary-linux.json')
feed={p:{m:read(folder/f'feed-all-summary-{m}.json') for m in ['q','r']} for p,folder in [('Mac',e),('ARM Linux',linux)]}
assert mac['pairs']==lin['pairs']==432 and not mac['errors'] and not lin['errors']
a=read(e/'final-audit.json');b=read(linux/'final-audit.json');sm=read(linux/'smoke-summary.json')
lines=['# combat4r 双端交付报告','',
'combat4r 包含 combat4q 搜索、30 份模拟器增量补丁、Nemesis 灼伤阈值修复，以及胜局最大生命上限收益评分。432 个固定状态的每个版本执行一次主搜索；确定性复查不参与结果选择。2000 局整局检验交由用户运行。','',
'## 固定状态对照','',
'|平台|状态数|4q 胜场|4r 胜场|共同胜场|共同胜场平均战后 HP，4q→4r|CPU 比，4r/4q|','|---|---:|---:|---:|---:|---:|---:|']
for p,x in [('Mac',mac),('ARM Linux',lin)]:lines.append(f"|{p}|432|{x['wins']['q']}|{x['wins']['r']}|{x['common_wins']}|{x['mean_hp']['q']:.3f}→{x['mean_hp']['r']:.3f}|{x['cpu_ratio']:.4f}|")
lines+=['',f"Mac 救回状态 {mac['rescued']}，退步状态 {mac['lost']}；ARM Linux 救回状态 {lin['rescued']}，退步状态 {lin['lost']}。共同胜场的 HP 比较不含单边胜局。CPU 比采用每次主调用的 `process_time` 总和之比；不含编译、重放、重复调用或队列等待。云端正式实验与验证共享机器，CPU 时间不能等同于独占机器的耗时。",'',
'固定输入来自 4q 交付的同一组 432 状态及轨迹，预算沿用来源：基础预算 40000、boss_multiplier=12；指定心脏状态的基础预算为 80000。首领战使用倍数，普通战斗使用基础预算。为避免机制修复改变战前路径，先在原 4q 导出战前 GameContext，再以独立 ABI 导入两包。432 个导出状态通过原入口指纹检查，以及保存动作重放后的奖励／事件回调状态一致性检查。每个平台的 4q 复跑与该平台旧交付记录核对，结果见下方证据。父版本在两平台的固定状态结果存在差异；本次确定性验证范围为各平台对应编译包内部。云端基线编号 397 按父记录 CPU 耗时分配到空闲计算槽，主队列复用完成结果；文件哈希确认没有重复覆盖，见 `evidence/baseline-parallel-397.json`。','',
'## 狂宴固定状态','',
'加上限率的分母是预选状态数；计入手动狂宴及破灭自动打出的狂宴。按动作前后上限变化、牌堆顶与消耗堆核对来源，药水果汁不计入狂宴。','',
'|平台／样本|状态数|加上限场数，4q→4r|加上限率，4q→4r|累计上限增长，4q→4r|','|---|---:|---:|---:|---:|']
for platform in ['Mac','ARM Linux']:
 for dataset,label in [('inputs','432 状态内含狂宴'),('feed-inputs','审计报告补充反例')]:
  q=feed[platform]['q'][dataset];z=feed[platform]['r'][dataset];n=q['states'];lines.append(f"|{platform}／{label}|{n}|{q['battles_with_feed_gain']}→{z['battles_with_feed_gain']}|{q['battles_with_feed_gain']/n:.1%}→{z['battles_with_feed_gain']/n:.1%}|{q['maxhp']}→{z['maxhp']}|")
lines+=['',
'两例补充状态固定为种子 3900012046／楼层 21、3900012581／楼层 37，来自审计报告原轨迹；两版本、两平台均获胜。`fixed-summary` 的旧 `feed` 字段统计手动动作；上表采用 `feed-all-summary` 与 `feed-growth-audit` 的回放校正值。此对照同时改变规则和评分，不能把全部差值归于评分。','',
'## 移植与评分','',
'[移植逐项清单](evidence/PORTING.md)列出 30 份补丁、来源、处理状态、测试入口与结果，并按卡牌审计八项反例列出验收。规则、局外效果、RNG 与点击动作域增量补丁均以零模糊应用，无冲突跳过。历史 `search_*.patch` 不重贴，避免覆盖 4q 自有搜索；早期规则修复继承 4q 基线并由回归套件覆盖。','',
'胜利终局增加 `100 × max(0, terminal.maxHp − combatEntry.maxHp)` 分；当前 HP 每点值 100 分。每点永久容量额外折合 1 点 HP，原 HP 项保留即时回血价值。容量影响换幕恢复和营火恢复，采用固定 1 HP 等价作为后续收益估值；该系数为启发式假设，未按本次结果拟合。战斗入口上限跨重规划和子树保留固定；死亡、逃跑、截断无上限奖励。9 组终局评分对照覆盖 0.5／1／2 HP 等价与 0／2／4 HP 代价，双端评分契约通过。','',
'## 验证','',
'- Mac 回归清单 469 个入口通过，包括独立 Java 保存场景对照。首轮 5 个外围文件缺失，补齐依赖快照后定向复测通过；首轮记录保留。',
'- Mac／ARM Linux 各 50 个机制探针、62 个状态探针，284 项数值检查通过。来源为卡牌审计原反例与对照，不用当前实现生成预期值。',
'- 双端各 432+2 个状态、每状态 q/r 两次主调用通过动作合法性、战后状态与 RNG 回放；GameContext 14 路 RNG 和新增回合结束洗牌状态纳入检查。',
'- 双端各 25 个主样本状态及 2 个补充状态执行相同状态、相同预算的第二次 4r 调用，返回结果和战后状态一致。',
'- 原版场景沿用来源中的 coverage_gap 标记，表示已比较字段吻合；这些检查不证明整套模拟器穷举一致性，也不证明整局胜率提升。','',
'## 云端冒烟','',
f"{sm['games']} 局：error 全为 null，{sm['heart_wins']} 胜、{sm['games']-sm['heart_wins']} 败。固定种子 3000000000–3000000007。实际调用 c4r {sm['c4r_calls']} 次，其中 heart2 心脏预算检查 {sm['heart2_calls']} 次。",'',
'`sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3`','',
'首次云端编译被 macOS 归档中的 `._` 元数据文件打断，排除该元数据后构建通过；失败目录与日志保留。首次冒烟启动发生在包装前，父版本 manifest 拒绝加载，未产生战斗结果；包装后执行同一组 8 个种子。空输出和启动日志保留，未丢弃实战结果。','',
'## 交付入口与来源','',
'- Mac：`/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-combat4r/runtime-delivery`。',
'- ARM Linux：`~/sts/combat4r/runtime-delivery`。',
'- 调用：`C.F.resolve_combat4r(gc, budget, boss_multiplier)`；通过 `P300_RUNTIME` 指向对应目录。',
'- 云端驱动：`~/sts/principles/agent/p300_play_v15.py`，由 v12 加一个位于 c4q 前的 c4r 分支生成；heart2 心脏预算 80000，其余 40000。v12/v13/v14 未写入。',
'- 本机驱动：`/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-principles/agent/p300_play.py`，最小插入 c4r 分支；插入前后除该片段外字节相同，交付时检查分支存在。',
'- 编译使用父版本平台 flags、PGO、模型与依赖；编译单进程，云端 linker 1 线程。云端测试至多 4 个计算进程，本机至多 8 个。',
'- 对齐项目按只读来源复制，592 个快照文件的 SHA256 见 [snapshot-manifest.json](snapshot-manifest.json)；Mac 保留快照内容。两端父运行包 80 个文件及父源码 88 个文件哈希未变。两端新 C++ 源码 89 个文件与预期哈希吻合。','',
'|平台|fightsim SHA256|slaythespire SHA256|','|---|---|---|']
for platform,x in [('Mac',a),('ARM Linux',b)]:lines.append(f"|{platform}|`{x['runtime_identity']['fightsim_sha256']}`|`{x['runtime_identity']['engine_sha256']}`|")
lines+=['',
'构建命令与源文件／二进制哈希见各平台 `runtime-delivery/combat4r-build.json`，父版本材料在 `parent-combat4q-provenance/`；外部 PGO／JSON 头文件与编译器版本见各平台 `evidence/build-input-identity.json`。','',
'## 证据入口','',
'- [Mac 固定状态汇总](evidence/mac-final/fixed-summary-mac.json)、[ARM Linux 汇总](evidence/linux-final/fixed-summary-linux.json)。',
'- [Mac 狂宴逐动作记录](evidence/mac-final/feed-growth-audit-r.json)、[ARM Linux 记录](evidence/linux-final/feed-growth-audit-r.json)。',
'- [Mac 4q 历史复现](evidence/mac-final/q-reproduction-mac.json)、[ARM Linux 4q 历史复现](evidence/q-reproduction-linux.json)。',
'- [Mac 文件与回放验收](evidence/mac-final/final-audit.json)、[ARM Linux 验收](evidence/linux-final/final-audit.json)。',
'- [Mac 单元测试汇总](evidence/mac-final/test-summary-mac.json)、[卡牌审计检查](evidence/mac-final/card-audit-validation.json)、[冒烟汇总](evidence/linux-final/smoke-summary.json)。',
'- [输入清单](inputs/manifest.json)、[完整移植差异](evidence/combat4q-to-combat4r.patch)。云端原始固定状态结果保留在 `~/sts/combat4r/evidence/fixed/`；Mac 保存云端紧凑结果与原始文件哈希，未下载全部原始日志。','']
(r/'report.md').write_text('\n'.join(lines))
print(r/'report.md')
