# E133: learn first-Act card and later relic decisions from complete continuations

> 状态更新：E133 在 2026-09-22 取消采样，训练未启动。产物保留且未准入学习，见 [取消记录](e133-cancelled.md)。下文保留原设计与启动状态。

E131 found eight known fit families whose winning early-card routes were absent from every measured old-scope combination. E133 tests whether a policy can learn useful early choices from that scope. The first decision is the final card offer after Act 1's first fight. Each card branch generates its own later first-boss relic menu, and the model chooses from that actual menu. All other decisions use the frozen parent; combat remains MCTS 8,000, boss multiplier 3 and 256 replans. Scope is Ironclad A20 natural start through keys, both Act-3 bosses, Shield/Spear and Heart, excluding Prismatic Shard.

## Data and learning contract

The fit and label-holdout families are exactly the original E128 small-fit 1,536 and common holdout 1,024. Forty-two fit families reuse E131's audited complete trees; new collection covers 1,494 fit and 1,024 holdout families. The other pilot families are not added. The 512 natural-development families retain their separate role. Errors cannot become deaths, and families that fail before an intervention remain in the denominator.

The candidate freezes the same 192-dimensional parent representation and learns a card readout and relic readout with option biases. Support and RMS scaling come from fit families only. A fixed parent-action bonus of one preserves the parent's choices with zero readout weights. If an offer contains an identity outside the fit support, the whole offer uses the parent.

The objective averages terminal Heart outcomes over every assigned fit family. A card's expected outcome uses the probabilities of the **actual later relic policy** on that card's branch. It does not assume that a future agent always picks the winning relic. Earlier-floor survival supplies no substitute reward. One candidate receives 1,000 Adam updates at learning rate .03, L2 .001 and gradient norm limit 1. There is no parameter sweep, checkpoint selection or repeated holdout search. The final checkpoint is frozen before the common holdout is scored.

The 1,024-family holdout requires at least 20 net wins over the parent and paired exact p < .05, with all reachable chosen card/relic nodes checked in real simulator states against independent native action decoding and readout arithmetic. Only a passing candidate enters the 512 natural-development games. That phase requires at least ten net wins and p < .05, zero execution faults, full independent outside-NN/state/RNG audits, and fresh NN/MCTS replanning of every winner. First differences must occur at a permitted card or relic choice. Winning routes must contain all three keys, two distinct Act-3 bosses, Shield/Spear and Heart. Adoption is not automatic. The common holdout is development evidence with historical exposure; final acceptance still requires a frozen candidate on 1,024 genuinely unseen families and at least 512 wins.

## Preparation and execution evidence

Six learner checks, two role/admission checks, three native replay checks and six experiment-entry checks pass. Four existing fit-source routes were used without new outcome selection. The checks cover the joint probability objective, a synthetic joint-only winning branch, frozen parent weights, fit-only normalization, unsupported-offer fallback, checkpoint loading, nonzero readouts at real states, wrong terminal rejection and action-scope enforcement. An initial native test expected boss skip ID -1; the existing interface uses `RELIC_CAP`. The test fixture was corrected without changing production behavior, and the initial two passes/one failure and final three passes remain local.

The final learner and experiment entry were frozen. Running the real entry against pending collection evidence rejected the missing `data-execution-completion.json` before creating either a learning directory or a training execution. The prepared controller writes stdout/stderr to a durable regular log file, using the E128 recovery launch primitive. The original collector, source, test inputs and runtime hashes were checked unchanged after training preparation. These checks do not stand in for a completed formal fit or 512-game candidate run.

Sampling launched on September 22 at 05:04 Shanghai with eight single-thread workers. Batches contain at most 256 jobs to bound retained trace memory. Limits are 81,920 new continuations, 24 hours of collection and four hours of independent audit; these are caps, not duration estimates. Formal candidate fitting has not started. The main task owns repairs, design, launch, analysis and the next action. Luna owns waiting, taking one bounded observation every 20 minutes and returning complete data or a fault. Ending a waiting turn does not pause the project.

The private study is `runs/heart-e133-early-card-learning-20260922-01`. Collection writes `data-execution-completion.json`, `data/label-verification.json` and owned collect/audit process exits. Training is a separate launch after the main task admits that completed evidence:

```text
<python> <study>/learning-program/heart_early_card_experiment.py check --study <study>
```

After admission, launch `<study>/learning-control/controller.py` with `heart_training_resume.detached`, a new exclusive `learning-control/controller.log`, and the study as cwd; record the PID, command and registration hash. Do not rerun an existing execution or start training while labels are pending. The controller invokes train, verify, conditional natural development and finalize, with owned stage deadlines and cleanup. Luna does not launch training or choose the next experiment.

The frozen protocol, launch, preparation and source hashes are in [the aggregate record](e133-early-card-learning.json). Raw family IDs, traces, labels and weights stay local. [E131's completed diagnostic](e131-scope-result.md) explains the reason for this experiment; it is not evidence of a learned-policy gain.
