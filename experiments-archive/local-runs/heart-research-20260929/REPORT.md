# StS A20 铁甲心脏研究交付（2026-09-29）

**目标云端的提胜率收益尚未证实。** `spear160` 是本机证据最强的实验候选：盾矛入口固定预算80000→160000，心脏保持80000×boss12。开发24根救回2局/损失1局，留出46根救回1局/损失0局；合计70根救回3局/损失1局。本机留出投影 **+0.92个百分点**，合计投影+1.23个百分点。但这4个胜负分歧种子在云端重算均为基线败/候选败，**0救回/0损失**，本机3个救回没有在这组云端复查中复现。样本区间包含零，不能宣称当前47–48%的云端胜率已经提高。

入场血量是最强描述性区分因素：c38心脏胜局战前HP均值73.83，败局49.04，最大HP均值接近。差距主要在盾矛战扩大：两组盾矛入口78.49/75.37HP，盾矛净掉血5.19/27.16HP。这支持检验盾矛搜索；它不证明多回血就能获胜。

## 按收益证据排列的行动清单

| 规则/改法 | 确定性救回/损失 | 整局收益投影 | 本机CPU代价 | 处理 |
|---|---|---|---|---|
| spear160：盾矛160k；心脏80k | 本机开发2/1；留出1/0；云端分歧4例0/0 | +0.92pp（本机留出）；云端未知 | 本机留出后缀25.81→26.03秒（+0.9%） | 实验优先级1；云端收益未复现 |
| hrest90：第四幕营火HP<90%休息；排除禁止/阻止回血遗物 | 73根7/5；开发2/4、留出5/1 | +0.20pp（c38触发根枚举） | 后缀39.89→41.60秒（+4.3%）；无额外搜索调用 | 方向不稳定；独立实验开关 |
| 仅心脏切combat3推演 | 开发48根3/2 | +0.61pp（开发筛选值） | 心脏CPU×1.15 | 没有独立留出确认；不列入推荐配置 |
| 心脏160k / 320k | 开发48根均0/0 | 0pp（样本） | 心脏CPU×2.22 / ×4.27 | 缺少收益证据 |
| heart40：心脏40k；盾矛80k | 开发1/0；留出0/1；合计1/1 | -0.31pp（留出）；0pp（合计） | 留出心脏CPU−44.5% | 保留算力对照开关；不是提胜率建议 |
| 后期强选首张FNP/DE/Second Wind/Disarm | 12根0/2 | -0.20pp | 后缀CPU×2.45，含1177秒长尾 | 不采用 |
| 第四幕商店指定药水优先于其它购置 | 48根1/4；留出0/2 | -1.96pp（314个触发根投影） | 后缀CPU×0.94 | 不采用 |

pp=百分点。不同实验的CPU起止位置不同，不能横向相加。收益来自本机固定历史前缀，不是新种子的整局实测；macOS与Linux搜索输出存在差异。Spear留出按自然分布加权的成本投影为每次整局开局+1.28本机CPU秒。规则之间没有组合对照，不能相加收益。

## 画像、机制与反例

- c38共1000局：482心脏胜、147心脏负、22盾矛负；c37不重叠后1000种子提供630个心脏入口作描述性复核。1309份第四幕历史轨迹的动作与终局重放通过。
- 58/147心脏败局在T2–3结束；86局死于结束回合序列，61局死于出牌序列。选牌暂停后的敌人伤害归入原结束回合序列，不能把所有CARD/SELECT死亡都标为死亡律动。
- A20 Invincible额度为200，Beat of Death开局2，Blood Shots基础2×15。Invincible在心脏回合开始重置；反伤可以使按玩家回合汇总的HP下降超过200。
- Dark Embrace、Feel No Pain、Dead Branch、Apparition及部分防御药水存在跨样本正关联；Demon Form等关联不稳定。格挡牌数量本身的区分度低，消耗/过牌引擎与余血更有信息。关联不能代替选牌或购置对照。
- 状态牌堵手存在个案，但败局T2起手的状态/诅咒牌数量没有高于胜局。源码包含Evolve抽牌与Void失能量处理；本研究没有证明这些机制缺失。
- 147个败局中146局最终无药，1局剩烟雾弹；主要问题不表现为一直囤药。2947的T1速度药无终局收益，移到T2后原记录序列结束时存活但战斗未结束，该诊断不计救回。
- 2803的少预算救回线在T6跳过0能量旋风斩，保留2格挡并在T7部署引擎；留出2594却因减预算由胜转负，排除了“少搜必然更好”的解释。
- 盾矛候选救回2154时，心脏入口79→84HP；损失2688时，入口28→50HP却转负。2719两线都是126HP、同种药水也有不同结局。后续RNG与遗物/奖励状态可以随合法动作改变，不能把收益全部归因于HP。
- 商店2255初始130金币，抢购110金币复活药挤掉84金币黑暗之拥，两线进心脏均40HP且无药，基线胜、候选负。药水优先需要考虑机会成本。

逐回合原始顺序与解释：[五个典型败局](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/cases.md)、[预算救回反例](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/budget-case.md)、[盾矛全部四个胜负分歧](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/spear-cases.md)。完整画像（HP、卡组、遗物、药水、钥匙路线）：[profile.md](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/profile.md)。

## 实现与验证

本机入口：`agent/p300_play.py`。云端新文件：`~/sts/principles/agent/p300_play_v14.py`，由冻结v12加三个独立开关生成；v12/v13与运行包没有被本任务修改。完整增量：[delivery/v12-to-v14.patch](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/delivery/v12-to-v14.patch)。本机已有c4r等其它工作保留，未混入云端v14。

原arms后追加 `+spear160` 即为候选1；另建一臂追加 `+hrest90`。它们是供用户整局验收的实验开关，不是已接纳的新主配置。`+heart40`供算力权衡实验，不应凭开发集的单次救回合并进主配置。三个开关彼此独立；未启用时，v14与冻结v12的策略结构对照通过。

| 云端自然整局冒烟 | 局数 | 胜/负 | 执行错误 | 动作前缀 |
|---|---|---|---|---|
| heart40 | 8 | 4/4 | 0 | 直到开关触发前与v12历史记录一致 |
| hrest90 | 8 | 6/2 | 0 | 直到开关触发前与v12历史记录一致 |
| spear160 | 8 | 3/5 | 0 | 直到开关触发前与v12历史记录一致 |

838条主实验搜索/分叉终局结果完成；869项重放审计通过（其中含复用病例检查，不是869个独立样本）。73个营火根验证交付规则与被测规则的动作一致。预算分发覆盖9个场景；云端24局自然轨迹合法性与终局重放通过。冒烟不是胜率检验。2000局整局验收由用户执行。

追加的云端4根×2后缀按本机胜负差异选样，只用于迁移核对，不进入总体收益估计。4个基线后缀逐动作复现c38记录，8条云端后缀的合法动作与终局重放通过。结果与限制见 [云端迁移复查](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/cloud-portability/report.md)。

本机重型工作最多8个工作进程，云端研究最多4个；研究产物小于3GB。没有停止用户正式进程，没有Git提交/推送。依赖/运行包哈希、版本增量和最后交付哈希见manifest.json及delivery目录。

## 证据入口

- [心脏预算与局外准备对照](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/paired-results.md)；[盾矛固定预算对照](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/spear-results.md)。
- [搜索源码机制审计与后续可检验假设](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/search-audit.md)；[抽样、因果边界、加权与重跑命令](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/METHOD.md)。
- 逐局结果：[search-holdout.jsonl](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/search-holdout.jsonl)、[prep-results.jsonl](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/prep-results.jsonl)、[spear-results.jsonl](<repo-parent>/sts-rl-agent-principles/runs/heart-research-20260929/spear-results.jsonl)；每行包含seed、根指纹、游戏RNG、CPU、终局和动作/轨迹路径。
- 原始c38/c37摘要位于baseline；下载的轨迹子集位于traj；心脏逐动作证据位于traces；所有输入与交付索引见delivery/artifact-sha256.json。
