# E131: earlier card choices open winning routes outside the old scope

All 128 preassigned fit families completed. The study collected and independently audited 2,020 continuations, checked every family's outside-policy/state/RNG route, and reproduced one winning route from each of eight new-rescue families with fresh natural-start NN/MCTS planning. Collection, audit and the durable controller exited 0 with clean shutdown. The main task checked the proof chain and reconstructed the complete comparison from the trees.

| Measured choices | Families with a winning measured continuation / 128 |
| --- | ---: |
| Parent decisions | 16 |
| First Act-1 card alone | 26 |
| First boss relic alone | 18 |
| First Act-1 card then branch-local first boss relic | 32 |
| Previous scope: first boss relic then first Act-2 card | 27 |

These counts select actions with knowledge of terminal outcomes. They are not results from a trained model. The early-card scope has 31 families with both winning and losing branches. Eight families have a winning early-card combination while all measured old-scope combinations lose; three have a win only in the old scope. Five families require both changes within the early-card scope, and two of those five are among the eight new rescues. The expansion gate uses **eight new rescues**, not five joint-only rescues. Two original Act-1 deaths have winning early-card branches.

The original gate required 128 complete families, zero faults, at least 16 mixed families, at least four new-rescue families and complete fresh replanning of the new rescues. It passed. The result supports spending data budget on the earlier decision scope. It does not show that the winning choices can be predicted from public state or that a learned policy wins 32/128.

Decision: E133 uses the exact original 1,536 small-fit families and 1,024 common label-holdout families. Their outcome-independent intersection with this pilot contains 42 fit families, whose audited trees are reused once. The other 86 pilot families are not added. The frozen parent encoder, combat budget and single fixed training recipe remain the same so the new experiment tests learning in the earlier scope.

There were zero optimizer updates, candidate adoptions or unseen acceptance games in E131. [Aggregate evidence and hashes](e131-scope-result.json), [E133 design and execution](e133-early-card-learning.md). The original frozen E131 design and launch records remain unchanged.
