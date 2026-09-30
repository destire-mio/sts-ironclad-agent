live4 当前工作入口：live4/CONTINUE.md。run.sh 指向 live4/cli.py。历史记录在下文，现状以 live3/teacher 和 live4/student 的 JSON 为准。

当前入口更新（2026-09-30）：第三轮中间交付在 `live3/`，运行用本目录 `run.sh`。学生16局终局、0故障，老师前12/100局终局、0故障，剩余88局。当前无运行中的本任务Java。第三轮记录与版本边界见 `live3/CONTINUE.md`、`README.md` 和 `../../scratchpad/parity/live3-report.md`。续跑命令 `./run.sh --policy teacher`；跳过本轮任何已尝试种子，不重跑旧局。下文为前两轮历史记录，不代表第三轮现状。

本任务进行中：在原版 Java 中执行种子 3900002000–3900002099，目标 100，至少 50 完整终局；故障单列。开始 UTC 2026-09-28 17:37:50，8 小时截止。原始仓库及云端保持只读；新代码、证据均在本目录。最终报告写 ../../scratchpad/parity/live-report.md，中文结论先行，≤1500 字，最终答复同正文。

当前运行：`drain_restart.py --workers 4` 启动 `batch.py --games 100 --workers 4`，日志 batch-four.log，状态 cohort/progress.json。4 个原版实例上限；可写 worker-limit.json 为 {"workers":2}，让现有局结束后降并行。不要杀正在打的局来调并行。batch 固定初始截止时间。pack.py --watch 对完成证据做无损 xz 压缩。

Python：python。读原始记录用 analyze.record_stream（支持未压缩、gzip、xz）。`python3 analyze.py` 更新 summary.json、per-game.jsonl、per-game.md。自动生成报告模板可用 --report，但最终正文应根据全部结果重写、检查字数和限制，不照搬中间结论。

参考：cloud-reference.json 为 c23 前 100 种子，39 胜。cloud-inputs.json、cloud-artifacts.json 保存只读云端核对；P300 脚本、guide、relic_u、价值表、模型和配置与 Mac 相同，平台二进制不同。模拟器 Mac 对照因内存压力在 11 个完整结果后停止，simulator/pool-interruption.json 记录停止的本任务进程；这 11 个胜负/终局楼层均与云端相同。无需恢复额外 Mac 批次。

接入：runner.py 复用 sts-rl-agent-live-original/steam/live_run.py，Policy 从冻结 p300_play.play 的 AST 提取局外决策体，规则顺序原样保留。新 live_combat_search 扩展复用指定 combat4 静态库与原始 header，调用 playoutReusing(...,true,true)。binding-check.json 验证普通战/Boss 的计划、动作、搜索量一致；147 个局外决策与生产轨迹相同。

驱动不读档、不恢复 RNG、不换种子。同一实际状态只规划一次；执行后出现分歧则从新的原版状态重规划，不回滚战斗。每层规则时间 = floor*45，与模拟器配置匹配。完整命令和状态逐条落盘。Original.rpc 内存缓存已清掉（Probe 仍流式保存完整 RPC），避免长局重复缓存耗尽内存。当前驱动以导入时源码哈希记录版本；最早几局的哈希修正在 early-driver-provenance.json。

已见故障：2002 FaceTrader 开场对白；2007 Singing Bowl 指令；2008 Winding Halls 开场对白；2014 WeMeetAgain 无金币选项的 Java 0/native -1 哨兵差异。修正仅在本目录 runner.py，新局使用；旧故障保留，未重试。event-legality-check.json 对 2014 原版现场验证修正后 legal indices [2,3]。

后续明确的未支持场景：2013、2019 获得 Toolbox 后进入新战斗，开场 CARD_REWARD 选择发生于抽牌/其他遗物队列执行前，当前 bridge 不能重建该待执行队列，因此记录故障。不要随意选择第一张来冒充 combat4 的选择。已开始第 20 多号种子，完成数量和胜率查询最新文件。

新增 audit.py 用于最后检查所有完成终局的原版 victory flag、seed/A20、一次自然 start、仅 observe/command RPC、所有实例 cleanup=[]，并列出残留原版 Java 进程。analyze.py 还输出 100 指定种子的原版胜率硬界（未知故障全败/全胜）和 Mac 11 局控制检查。resume.sh 给未来用户续跑分配新会话预算，当前 batch 使用 plan.json 的初始 8 小时截止。

进度以文件为准。已见原版心脏胜种子 2001、2006、2011（均前缀 390000）；terminal.json.gz screen_state.victory=true、act=4。2003 是模拟器胜/原版心脏死。trajectory-3900002003.json 为保存模拟器动作的只读重放：前 4 战计划相同，第 6 层 Lagavulin 搜索计划不同，第 7 层原版多 5 HP，第 32 层原版休息/模拟器升级，之后牌组分叉。不得把该链条写成已证明的败局原因；未做反事实因果试验。

最终工作：完成批次（或 8 小时截止）→检查每局终局胜利 flag、种子、A20、清理 remaining=[]→汇总完成对的胜率/配对一致率/独赢数/置信区间、故障数和机制→保存报告，全文交付。故障与未完成均不计胜負；报告说明故障排除产生选择偏差。统计区间采用配对独赢类别的 Clopper-Pearson + Bonferroni 保守精确区间，零分歧时非零宽度。结束必须清理所有本任务原版进程（仅 /ironclad-alignment/live/ 下实例）。不要触碰云上 60 worker 正式实验。

恢复命令：./resume.sh（跳过完成/故障种子，按新会话预算继续未尝试种子）。若当前批次结束早于 100，先分析原因，不用重跑已完成局补指标。

本次用过记忆 MEMORY.md:225-231（旧原版接入记录定位），最终需添加一个 memory citation block，rollout id 01a0e143-ded9-7e32-82bd-f894ea418b09。所有当前结论须来自本次证据。

## Ongoing update around 2026-09-28 19:00 UTC

- Still running the same four-worker dispatcher (batch-four.log). Do not end the task: finish all 100 assigned attempts, at least 50 terminal runs, within deadline 2026-09-29 01:37:50 UTC.
- Latest status: 40 complete, original 14 wins / 26 losses; matched c23 17 wins. Original-only 1, simulator-only 4. 11 faults. 4 active, 45 pending. Free disk about 3.3 GB; memory free 44% at last read.
- Fast status command: `python3 ironclad-alignment/live/status.py` (add `--faults` for all fault errors).
- Added `count_imports.py`, and `import-count-reconstruction.json`: exact reconstruction of missing early sync counters from decisions + battle entries + recovery events + plans. Seed 2002 has one post-import selector failure. Validated reconstructed counts against instrumented seeds 2005 and 2006. Analyzer now uses these exact counts rather than an estimate.
- Added a runner Search subclass handling Java confirmation between duplicated Armaments selections. Old logic fails when native is already at the second CARD_SELECT while Java awaits confirmation of the first. Strict guard requires full selected HAND_SELECT, no `choose`, `confirm` available, no pending multi. `hand-confirmation-check.json` applies five saved actions to the archived seed 3900002036 snapshot, no search and no Java replay: old false/new true at the failing selection; both false before selection. The failed run was not repeated.
- Added explicit Match and Keep unsupported-board guard before policy import. Original seed 3900002044 failed floor 37 RULE_EXPLANATION with IndexError because native board/memory were not imported. Future occurrences fail clearly before choosing. Do not fabricate a board or select a default card.
- Faults now include: 2002 FaceTrader intro, 2007 Bowl command, 2008 Winding Halls intro, 2014 WeMeetAgain disabled option, 2036 duplicated Armaments confirmation (all fixed only for later runs); Toolbox pending queue seeds 2013,2019,2031,2041; Gambling Chip 2029; Match and Keep 2044. Analyzer groups fault mechanisms from snapshots.
- First original-only winner seed 3900002045: original Heart win floor 57, 1 HP; cloud simulator death floor 33. Ran exactly one additional Mac simulator diagnostic for 2045 with `simulate_one.py` (finished; process/session 79892 ended), which also died floor 33. There are now 12 Mac controls: initial 11 plus this outcome-selected diagnostic; do not portray the selected diagnostic as an unbiased extra sample.
- `trajectory-3900002045.json` / log compare saved simulator actions without search or original replay: common outside actions identical through simulator death; first saved combat-plan fork floor 7, then HP/maxHP differ. `plan-differences-3900002045.json` holds saved plan comparison. Native root HP at floor 33 original 58 vs sim 57, maxHP 86 vs 89. Original beats Automaton with 8 HP. This supports battle-plan path differences, not a proven engine/root cause.
- Existing seed 2003 diagnostic: first plan fork floor 6, HP difference floor 7, outside rest vs smith fork floor 32, original Heart loss vs sim win. Root text differs in loopCount and unique IDs; do not claim these cause the search difference. Source inspection shows loopCount is a million-action loop guard, no causal test performed.
- `analyze.py` table now explicitly defines first divergence as one-step simulator prediction from imported original state vs Java observation; it is NOT the first fork of independent whole-run paths. Sync count includes normal GameContext + BattleContext imports. Full traces preserve every step.
- `audit.py` now also checks 40000 simulations, 12.0 boss multiplier, requested arm, frozen runtime manifest. Final full audit still required; prior audit covered 20 terminals and confirmed no reload/replay.
- `resume.sh` shell syntax checked. It resumes unattempted seeds, skips completed and failed attempts. No report finalized yet. Final Chinese report <=1500 chars/words at scratchpad/parity/live-report.md and same text in final; appendix memory citation required (MEMORY.md:225-231, rollout 01a0e143-ded9-7e32-82bd-f894ea418b09).

## Further ongoing update, 2026-09-28 19:41 UTC

- Latest live status: 63 terminal pairs, original 22 wins vs cloud 23 wins; original-only 3, simulator-only 4. 20 faults. 4 active and 13 pending (seeds through 2086 started). Continue all 100 attempts; do not finalize while pending/active remain.
- New `write_report.py` builds a <=1500-character Chinese report from `summary.json`. `--interim` permits active batch; final (no flag) asserts 100 unique attempts, >=50 terminals, final audit terminal count matches, zero Java remnants. Current scratchpad/parity/live-report.md is an explicitly labeled interim report; final must overwrite then copy the same body into final response, append required memory citation.
- New faults: 2057/2059 Gambling Chip, 2060/2062 card identity absent in selection, 2071 Wheel of Change missing native continuation, 2072 The Joust missing continuation, 2075/2084 Match and Keep, 2081 Toolbox. Existing analyzer now classifies these from fault snapshots; no original fault was rerun.
- Investigated identity errors with `inspect_selection_identity.py`: reconstruct final saved plan using recorded actions only (no search, no Java replay). In 2060, Corruption exhausts Armaments and Dead Branch makes a new Battle Trance immediately before its picker. Mapping only refreshed at PLAYER_NORMAL, so new UUID absent. All four ordered piles match; new runner Search._selection_uuid refreshes existing mapper ONLY when target UID absent AND all four ordered piles fully match. Target native action unchanged; picks `choose 7` (Battle Trance); battle fingerprint unchanged. In 2062, Armaments picker filters hand (target Impervious), full hand mismatches, so the guard retains the original fault. Both positive and negative archived-state checks passed; see identity-diagnostic-<seed>.json. Repair applies only later freshly started seeds. Result telemetry `selection_identity_refreshes` counts actual new mapping refreshes (none among first completed after change at last check).
- New Search.next_action caches current view for selection identity refresh. No policy, search budget, or native engine change. All completed runs' capture_code_sha256 still one version (common pre-existing bridge source untouched); task-owned driver versions vary and are preserved per run.
- Report now states per-floor 45-second rule-time input. Faults preserved, diagnostics do not change outcomes. Majority of recent faults are known queue/board/continuation gaps; no broad fallback choosing alternate cards or default actions.
- `simulator/diagnostic-seeds.json` records outcome-selected diagnostic 2045. Analyzer excludes it from paired_mac/control statistics; includes it as explicit diagnostic and preserves its original/cloud pair in the primary sample. Initial Mac control has 11 completed rows (seeds 2000..2009 plus 2012, completion-selected after interruption), not a contiguous first 11. Total Mac simulations =12; all 12 match cloud win and terminal floor, but no global bitwise/platform equivalence claim.
- Analyzer's combat_replans now equals successful plan count minus battles with a plan; raw result resynchronizations is a separate field because it may include run recovery.
- One commentary typo was immediately corrected: at 50 completed, agreement was 44/50 (88%), not 46/50. Generated summary/report math was always correct. Copy generated final numbers rather than mentally recomputing them.
- Final tasks: wait for batch+pack exit; ensure all 100 unique seeds; run pack once if needed; analyze.py; audit.py (full final, prior audit was only 20 terminals); ps verify no owned Java; write_report.py; inspect final report length/links; final same text + one memory citation. Stop any leftover owned pack/dispatcher processes as appropriate, never kill unrelated processes. All new scripts under live; cloud remains read-only.

- Memory citation line check with `nl -ba` confirms the relevant nonblank registry entries are MEMORY.md:226-228 (not 225-231, which includes blank boundary lines); use 226-228, same rollout ID 01a0e143-ded9-7e32-82bd-f894ea418b09.
- Latest after this update: 72 terminals, original 24 wins vs c23 25; 21 faults (new 2090 Gambling Chip at floor 51). Only six seeds pending. Final full audit and cleanup still required.

## COMPLETED 2026-09-28T20:01:03.819393+00:00

100 assigned attempts ended: 77 terminals (27 wins, 50 losses), 23 faults. Matched c23: 27 wins/77; both win 22, both lose 45, original-only 5, simulator-only 5; agreement 87.0%. All 100 archives packed. Final audit verified 77 terminal flags, all fault seeds, 100 starts, 81,413 commands, no reset/replay RPCs, and zero owned Java processes. Dispatcher and pack watcher exited. Final report is scratchpad/parity/live-report.md (under 1500 characters including links); summary.json, per-game.md/jsonl and audit.json finalized. No further task work pending.
