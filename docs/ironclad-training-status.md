# Ironclad A20 training status

Updated 2026-09-19. Scope: Ironclad, Ascension 20, natural start through the Heart, including three keys, two Act 3 bosses, and Act 4. Prismatic Shard is excluded. Combat uses MCTS; a neural policy controls out-of-combat decisions.

The current engine is the E66 rule/RNG repair. Under that engine, the existing E61-selected policy completed E67 with **255/2,560 Heart wins (9.9609%)** and zero execution faults. The preassigned roles contain 156/1,536 fit wins, 46/512 label-holdout wins, and 53/512 development wins. All 2,560 terminal states/RNG, 347,087 outside-NN choices, and fresh replans of all 255 winners passed verification. Nine Act-3-without-Heart endings remain failures. This is the repaired-engine source baseline, not a new trained model result.

The user authorized publishing the work and pursuing a 50% win-rate target. Acceptance means at least 512 Heart wins on 1,024 seed families outside all training, tuning, and model selection, with a frozen model/runtime, confidence interval, explicit execution failures, and full replay verification. E67's assigned families are development material and cannot serve as that final test. Original-game parity and simulator win rate remain separate claims.

## Current experiments

**E69 completed and both candidates were rejected.** All 6,324 terminal/RNG checks, 919,839 nonintervention NN choices and 1,581 newly planned parent-choice controls passed; 467 early failures remain in the denominator. Static 23-parameter scores produced 170/1,536 fit wins and 50/512 heldout wins, versus 156 and 46. Its +6/−2 heldout pairs failed the registered gate (p=.2891). The 92,407-parameter contextual network reached 221/1,536 fit wins but 25/512 heldout (+7/−28,p=.0005083). Live choices matched reconstructed labels. Neither entered natural development. Completion SHA: `a6c7004697660fad423c07c879ced29918ad93d940af3b935022eadd42f7df5f`. [Compact result](experiments/e69-contextual-relic-result.json).

E69's 210 informative fit families were memorized by that contextual recipe. For these cohorts and the fixed continuation policy, hindsight first-relic ceilings are 221/1,536 and 75/512; those are scope diagnostics, not deployable or population win rates. This evidence does not refute joint decisions or identify parameter count as the sole cause.

**E70 completed and passed its registered coverage gate.** All 1,640 terminal/RNG replays and 241,934 nonintervention NN choices passed, with zero execution faults. Its 128 preassigned fit families retain 24 first-boss failures. Parent wins were 22; relic-only, card-only and joint hindsight ceilings were 28, 31 and 37. Three families required both choices to change: neither single intervention could save them. There were 60 mixed card states across 35 families, and nine extra salvageable families over relic-only hindsight. No optimizer updates occurred. These hindsight numbers support further collection, not a learned or unseen-seed success rate. [Compact result](experiments/e70-joint-coverage-result.json).

**E71 was superseded before formal collection and optimizer updates.** Its immutable registration and known-seed software contracts remain. E69's overfit result motivated replacing that new-hidden-layer recipe; E70 continues unchanged.

**E73 passed preflight and is preparing the full joint cohort after E70 completed.** It freezes the existing 192-dimensional CardContextScorer representation and trains two small linear readouts plus option biases. A fixed one-point parent margin preserves parent behavior at zero weights. Public state and each current offered descriptor are the only features. Fit families are grouped into three deterministic folds, including all descendants and early failures. Supports and normalization come from each training fold only. Three predefined L2 values (.0001,.001,.01) each receive 1,000 updates; out-of-fold deterministic outcomes choose regularization inside fit only. With no qualifying internal improvement, save unchanged-parent heads and perform zero final updates. Otherwise refit for 1,000 updates on all fit families. All three ablations finish before external heldout use.

E73 reuses verified pilot leaves and the same full-data coverage gate (64 mixed card families and 30 extra hindsight-rescuable families), then applies the heldout and 512-natural-development gates (net>=10,p<.05,zero faults,full NN/terminal/RNG checks and winner replans). Its internal selection p-value is a development filter, not independent significance. Source model and combat stay frozen; main simulation pools run sequentially with 8 single-thread workers. Protocol SHA: `ac6439e1fbc0151d196cb8b8ff4e3bfbb3b7dcedd76614cbb34e89747717416f`. Formal optimizer updates and fresh 50% acceptance have not run.

E73 preflight: 24 focused tests passed. On one previously seen seed, zero heads and three 25-update software heads matched the selected table leaf and complete natural NN/MCTS route. All chose the existing parent route. A manual changed-combo fixture exercised both intervention paths and the native-option independent controller; three-arm live audit accepted correct choices and rejected a tampered expectation. These are software checks, not performance gains. Artifacts: `runs/heart-readout-learning-contract-20260919-01/`.

## Original-game alignment evidence

E66 repaired 20 confirmed E62 rule/RNG classes and the production potion-target bridge. Twelve recorded original-game action boundaries and eight natural-prefix boundaries match after repair. The 161-case CTest suite passed; ten new native groups fail on the prior source and pass after repair. The portable patch build passed 12 focused entry points. Potion bridge regressions passed five cases.

E68 replayed four preselected E67 development winners from natural original-game starts through A20 Heart victory. All 4,080 commands retained state/RNG checks, without state import or resynchronization. Split-slime target mapping was repaired, and the observer waits for the original exhaust-animation callback rather than assigning card costs. Initial failures remain in local evidence. The six slime-target regressions and five potion-target regressions pass. These four same-action traces do not establish a representative original-game win rate, live online model deployment, or exhaustive parity. See [the compact evidence report](../sim_patch/alignment/e68-natural-parity-report.json).

Historical E61 scored 121/1,024 simulator wins with an older engine. E62 found a first original-game divergence in each of those saved winning routes and stopped at that boundary; this does not establish original-game losses. Those old labels and the old win rate are not transferred to the repaired engine. E64/E66 repairs, rejected hypotheses, and evidence boundaries are retained in [the experiment archive](ironclad-experiments.md).

E72 checks two fixed winning combination branches from the same known E71 development seed. Both match natural original A20 Heart runs: Black Blood plus Seeing Red ends at 34 HP; Black Blood plus skipping that offer ends at 20 HP. All 2,047 recorded commands retain state/RNG comparisons, with no import or resynchronization. Original observer responses confirm Ironclad/A20, both Act 3 bosses, Shield/Spear, Heart, and all three keys. These are selected saved-action branches, not two independent seeds or deployed-model gains. The runtime and training protocols are unchanged. See [the compact combination report](../sim_patch/alignment/e72-joint-natural-parity-report.json).

## Training-code checks

Six E70 joint-policy checks and six E71 training-objective checks pass. A known development seed supplies a 4-by-4 real relic/card tree: every terminal branch is audited, and all three saved 25-update software-test models reproduce their selected branch from a natural NN/MCTS start, including the complete action prefix, terminal state, and RNG. The three results are win/win/loss; the failed joint arm is retained. This is a deployment contract, not training or generalization evidence.

Four branch-worker replans also reproduce the known leaves, and independent terminal/NN audits pass. Live choices from all three checkpoints match their tables; a deliberately incorrect expected relic choice is rejected. An independent decoder using native reward bits and Card objects verifies a changed-card full route and its permitted first difference. Formal E71 full-data stages remain unexecuted.

Historical trajectory tests require their original local artifacts and engines. Python caches native imports, so each module uses an isolated interpreter and its declared engine:

```bash
python tests/run_isolated.py --build /path/to/current/native/build --output /path/to/new/test-results
```

The earlier E68/E69 regression run covered 22 modules and 124 tests. A portal-trace module initially used the repaired engine and failed on an old RNG prefix; its declared historical engine passes, and the runner now assigns that engine. Those failures and the focused rerun remain recorded. The six E70 and six E71 checks above are subsequent focused runs, not a claim that a new aggregate suite was rerun. Local `runs/` archives are required for these historical tests; `sim_patch/alignment/` contains the distributable native regressions and original-game fixtures.

Raw models, game JARs, native binaries, and run traces remain local.
