from pathlib import Path
import json, sys

r = Path(__file__).resolve().parents[1]
out = r/'evidence/victory-hp'
s = json.loads((out/'summary.json').read_text())
a = json.loads((out/'final-audit.json').read_text())
identity = a['runtime_identity']
platform = 'Mac' if sys.platform == 'darwin' else 'ARM Linux'
f = s['fixed']
cpu = f['cpu_ratio']
strict, ties = len(f['strict_ranking_reversals']), len(f['tie_order_changes'])
feedrows = []
draft_note = ('首轮草稿验证后，复核发现实际回血提取遗漏表现层回调。修正并加入回调回归断言后，以最终二进制重新运行 432+2 状态；本表采用这轮结果。草稿二进制、源码、结果与弃用理由保存在 [草稿处置记录](revisions/victory-hp-projection-draft/disposition.json)，没有从两轮答案中择优。' if sys.platform == 'darwin' else '')
for dataset, label in [('inputs', '432 内含狂宴'), ('feed-inputs', '补充反例')]:
    q, n = s['feed_q'][dataset], s['feed_r'][dataset]
    feedrows.append(f"|{label}|{q['states']}|{q['battles_with_feed_gain']}→{n['battles_with_feed_gain']}|{q['maxhp']}→{n['maxhp']}|")
if sys.platform == 'darwin':
    cloud = '''云端新修订的交付、ARM 构建、432 对照与 8 局冒烟受当前会话网络沙箱阻塞。SSH 返回 `connect to host 47.101.206.226 port 22: Operation not permitted`，没有执行云端写入。本报告不将上一修订的 ARM 结果和冒烟结果计作本次结果。

更新材料见 [云端更新说明](cloud-update/README.md)、[源码更新归档](cloud-update/combat4r-victory-hp-update.tar.gz)；脚本在云端校验旧包、备份、原地更新 `~/sts/combat4r/runtime-delivery`，顺序编译，以 4 个计算进程测试，再执行固定种子 8 局冒烟。保持 v12/v13/v14/v15 和 4q 文件只读，不终止进程。脚本通过语法检查；ARM 执行待 SSH 可用。'''
else:
    smoke = a['cloud_smoke']
    cloud = f"云端同 arms 冒烟 8 局，error=null：8/8；心脏胜利 {smoke['heart_wins']}，c4r 调用 {smoke['c4r_calls']} 次，heart2 调用 {smoke['heart2_calls']} 次。种子为 3000000000–3000000007。[原始记录](evidence/victory-hp/smoke.jsonl)。"
text = f'''# combat4r 战后 HP 评分修订

修订标识：`victory-hp-20260929`。{platform} 运行包在原 combat4r 路径更新。胜利终局以胜利遗物结算后的 HP 评分；狂宴上限收益系数保持每点 100 分，搜索预算、其它评分项和入口签名保持原值。2000 局整局验收由用户运行。

## 规则与反例

评分在胜局中增加 `100 × (victoryHP − terminalHP)`，等价于把原来的当前 HP 项替换成胜利结算后的 HP。`victoryHP` 与实际退出战斗共享纯函数，按既有规则处理：带骨肉在当前 HP ≤ 一半上限时 +12，然后按遗物获得顺序处理燃烧之血 +6、黑暗之血 +12、圣职者面具 +1 上限及相应回血；魔法花放大回血，绽放印记禁止回血，结果受生命上限截断。

上限 80、带骨肉：39→51 的评分为 8600，41→41 为 7600（相同其它项）；旧评分为 7400 与 7600，测试确认排序反转。40/80 阈值、奇数上限、封顶、治疗禁用、遗物顺序、狂宴跨阈值、复制隔离、逃跑/死亡/截断控制组纳入单元测试。

当前引擎的胜利遗物回调没有独立掉血项，战内结算前的掉血保留在输入 HP 中。黑星影响奖励，血腥神像在金币领取时回血；奖励领取、换幕恢复、事件或下一房间入场不属于胜利遗物结算，评分不预支这些效果。投影不生成奖励、不调用退出回调、不推进 RNG。实际结算复用提取出的规则，原带骨肉阈值及遗物顺序保持原值。固定样本中有 {len(f['post_continuation_hp_changes'])} 个获胜状态在后续阶段继续改变 HP，逐项记录见汇总的 `post_continuation_hp_changes`；下表的战后 HP 采用完整退出状态，以保持与 4q 交付的统计口径一致。

## 432 固定状态对照

|平台|状态数|4q 胜场|新 4r 胜场|共同胜场|共同胜场平均战后 HP，4q→新 4r|CPU 比，新 4r/4q|
|---|---:|---:|---:|---:|---:|---:|
|{platform}|432|{f['wins']['q']}|{f['wins']['r']}|{f['common_wins']}|{f['mean_hp']['q']:.3f}→{f['mean_hp']['r']:.3f}|{cpu:.4f}|

救回状态：{f['rescued']}；退步状态：{f['lost']}。共同胜场 HP 不含单边胜局。CPU 是主调用 `process_time` 总和之比，不含回放与确定性复查；4q 的 CPU 来自同平台冻结的上次交付记录，本次没有重新测量 4q。原输入、预算、旧结果及父模块哈希经过核对，4q 的 432 结果在新证据目录中按原文件哈希复用。[冻结计划](evidence/victory-hp/plan.json)、[结果汇总](evidence/victory-hp/summary.json)。

基础预算沿原状态清单使用 40000 或心脏 80000，boss_multiplier=12。432 个新 4r 主调用每状态一次；第二次调用用于确定性断言，不参与结果选择。平台结果不能跨编译包当作同一确定性基线。

## 该项改变排序的触发次数

|指标|432 状态中的次数|
|---|---:|
|新方案获胜且战后 HP 与战内 HP 有差值|{f['winning_plans_with_hp_adjustment']}|
|旧、新 4r 返回方案均获胜，可比较排序|{f['ranking_comparable_winning_pairs']}|
|加入 HP 投影前后，两个方案的严格优劣反转|{strict}|
|加入 HP 投影前后，平分关系变化|{ties}|
|排序变化合计|{strict+ties}|

排序计数比较“上一修订 4r 返回方案”和“本次 4r 返回方案”：在同一套新机制中重放，分别用旧目标和新目标打分，比较分差符号。它不是树内每个候选节点的触发计数，也不把发生回血或动作变化当作排序反转。严格反转位置：{f['strict_ranking_reversals']}；平分关系变化位置：{f['tie_order_changes']}。逐项原始 HP、投影 HP、前后评分及分差见汇总中的 `ranking_evidence`。

## 狂宴样本

|样本|状态数|狂宴加上限场数，4q→新 4r|累计上限增长，4q→新 4r|
|---|---:|---:|---:|
{chr(10).join(feedrows)}

狂宴归因包含手动打出及破灭自动打出；果汁上限增长单独归因。2 个补充反例沿用种子 3900012046/楼层 21 与 3900012581/楼层 37，输入没有更换。上限收益评分保持原值，此表反映全部规则与评分的共同差异。

## 验证结果

- 新增胜利 HP 契约：25 场景、214 断言通过，含 39→51 与 41→41。狂宴原评分契约及 9 组系数敏感性输出通过。
- 50 个机制探针与 62 个状态探针，284 项数值检查通过；预期值来自冻结审计反例。
- 新 4r 的 432+2 个状态通过动作合法性、完整战后状态及 RNG 回放；旧 4r 的 434 个保存方案在新引擎回放，结算结果与旧记录一致。
- 25 个主样本状态及 2 个补充状态的同状态、同预算两次调用，返回结果与战后状态一致。
- 驱动 c4r 分支核验通过；Mac 的现有 p300_play.py 加载检查确认 C.F.resolve_combat4r 指向当前交付的两枚原生模块。云端驱动的执行以本修订冒烟状态为准。
- 90 个 C++ 源文件、父运行包 {a['parent_runtime_unchanged']} 个文件、父源码 {a['parent_source_unchanged']} 个文件、运行包 manifest 和验证文件哈希通过核验。[验收记录](evidence/victory-hp/final-audit.json)。
- 历史 469 项回归与原版对照属于上一修订证据，保存在[上一修订报告](revisions/pre-victory-hp/report.md)；本次没有将它们重跑。原版 `coverage_gap` 边界保持原证据含义。

{draft_note}

## 云端状态

{cloud}

冒烟 arms：`sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3`。

## 构建与交付

入口：`C.F.resolve_combat4r(gc, budget, boss_multiplier)`。{platform} 当前交付路径：`{r/'runtime-delivery'}`。

|{platform} 模块|SHA256|
|---|---|
|fightsim|`{identity['fightsim_sha256']}`|
|slaythespire|`{identity['engine_sha256']}`|

[构建记录](runtime-delivery/combat4r-build.json)保存源码哈希、二进制哈希、原平台编译命令和旧运行包身份；[运行包 manifest](runtime-delivery/manifest.json)绑定交付文件。沿用原 PGO/LTO flags；编译顺序执行，Linux linker 1 线程。Mac 测试最多 8 个计算进程，云端更新脚本限制 4 核和 4 个计算进程。

旧运行包与旧验证材料归档在 `revisions/pre-victory-hp/previous-delivery.tar.gz`。对齐项目的只读快照与 30 项移植、18 项继承、4 项历史搜索补丁处理状态见[移植清单](evidence/PORTING.md)；本次不新增机制补丁，不修改对齐项目或既有驱动。
'''
(r/'report.md').write_text(text)
print(r/'report.md')
