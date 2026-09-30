# 研究方法与重跑入口

基线为冻结的 cloud p300_play_v12.py，arms=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4q+heart2+fix2+baixi+eliteseek+fix3。源码、运行包、模型、配置和决策表 SHA 见 manifest.json；交付增量见 delivery/v12-to-v14.patch。

## 对照的含义

每个根状态从历史动作前缀重建。base 与候选初始记录字段指纹和游戏 RNG 状态一致；各自用同一种子、固定策略、一次 resolver 调用推进到心脏结束或此前死亡。候选改变动作后自然导致的 RNG 消费差异属于策略结果，不强行对齐之后的随机计数。每个候选的输出作为独立策略结果保存；不按每局胜负挑选候选，不随机重启。

根指纹覆盖观测、RNG、合法局外动作、outcome、encounter、牌组、repr 和可用的 transform preview 状态；它不是所有私有成员的独立序列化。历史轨迹含动作与战斗 outcome，但没有逐步私有状态指纹。1309 份历史前缀检查了动作合法性、战斗 outcome 和终局字段；这证明本次记录可重放，不是对原版全状态一致性的穷尽证明。

## 平台边界

相同根状态/游戏 RNG 下，macOS 与 Linux 搜索动作不同。Linux 的 8 个 smoke baseline Heart 搜索逐动作复现云端历史；macOS 不能用云端历史胜负当实验 base。重型效应对照均用本机新算的 base/candidate；云端 8 局自然运行用于检查交付策略、心脏前动作前缀和运行错误。未定位跨平台搜索差异的浮点或标准库来源。CPU 为每个工作进程的 process_time 秒，不能把 macOS 秒数当云端秒数。

## 预先规定的样本

Heart：c38 的历史胜、负各按 SHA256(十进制 seed) 排序。各取前24，共48个开发根；每层随后48，共96个留出根。开发比较 base80k、160k、320k、80k×boss6、combat3；80k×boss6 与 40k×boss12 在 Heart 上有效预算相同。低血量加预算的派生策略只依据根状态 HP<80%，不依据搜索结果。search-selection.json 在读取留出结果前冻结候选。

局外：743 份 c38 轨迹扫描到第三幕45层以后，重新计算13442个基线决策，动作差异0。每个规则每局取第一次与基线有分歧的状态。休息规则73个、后期引擎选牌12个全部评估；商店药水优先的314个触发根按同一哈希序取48个。各规则前半开发、后半留出。规则在 heart_prep_candidate.py；不根据候选胜负更换首动作。后续决策使用相同基线加该固定规则。

## 从条件收益估算整局收益

Heart 样本是历史胜/负分层抽样，不能直接用样本净胜/样本数乘0.629。估计为 0.482×历史胜层的候选减基线 + 0.147×历史负层的候选减基线。没有纳入尚未到心脏的局。休息、后期选牌枚举了c38对应触发根：净胜/1000；商店为 314/1000×样本条件净胜率。这些是冻结历史前缀上的投影，不是新种子的整局实测。

多个规则的收益不能相加：局外策略会改变心脏入口，搜索策略与其可能交互。开发集参与筛选，不能与留出集混为独立确认。区间采用救回概率与损失概率各97.5% Clopper-Pearson的Bonferroni差，避免0次差异产生零宽区间；分层整体区间还需按层计算。小样本或方向冲突不构成稳定提升证据。

## 重跑命令

本机环境：
```sh
export P300_RUNTIME=<repo-parent>/sts-rl-agent-combat4q/runtime-delivery
export PYTHONPATH=agent
PY=~/Documents/Codex/2026-09-10/new-chat-2/outputs/spire-lab/.venv/bin/python
"$PY" agent/heart_research.py search --paths runs/heart-research-20260929/search-holdout-paths.json --variants base:80000:12,boss6:80000:6 --workers 8 --output /tmp/heart-holdout-new.jsonl
"$PY" agent/heart_research.py prep --paths runs/heart-research-20260929/prep-jobs.json --workers 8 --output /tmp/heart-prep-new.jsonl
```
命令只是复查入口；本任务没有重复执行已有候选挑选较好结果。输出要求新路径，依赖文件需保持manifest版本；prep suffix默认写研究目录，复查时应改为新的 OUT 防止覆盖本次证据。

## 资源与交付边界

本机重型对照单个8进程池串行运行；云端最多4个研究工作进程。未执行2000局整局实验。下载为指定轨迹子集。正式云端v12/v13和运行包没有由本任务改动，正在运行的正式实验没有被停止。v14 是新文件；本机原始 p300_play.py 保存在 baseline/local-p300_play-before.py。没有 Git 提交或推送。

## 追加的盾矛预算假设

在心脏预算与局外规则对照结束阶段，根据“盾矛80k对心脏首轮960k”和盾矛净掉血的描述性证据，预先冻结spear-design.json。原历史心脏胜/心脏负/盾矛负各按seed哈希取前8个开发根，后16个留出根；盾矛负一共22个，因此其留出为14个。共70根×2固定策略，独立记录base与candidate，从盾矛入口推进到心脏终局；没有改变心脏预算。实现门槛在完整开发结果读取前规定为开发与留出加权终局收益均正。开发2救回/1损失，留出1救回/0损失，满足候选实现门槛；样本没有排除总体效果为零或负的可能性。

投影权重为0.482、0.147、0.022。留出点估计+0.91875个百分点，开发+1.8375个百分点，合计+1.225个百分点。它们不是三个独立实验，也不是整局实测。三类根过采样比例不同，CPU的简单样本平均和按自然人口加权后的增量不同：留出后缀平均CPU+0.9%，按原分布投影为每次整局开局+1.28本机CPU秒。
