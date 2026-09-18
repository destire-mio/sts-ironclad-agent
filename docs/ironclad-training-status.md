# Ironclad A20 training status

Updated 2026-09-19. Scope: Ironclad, Ascension 20, natural start through the Heart, including three keys, two Act 3 bosses, and Act 4. Prismatic Shard is excluded. Combat uses MCTS; a neural policy controls out-of-combat decisions.

The current engine is the E66 rule/RNG repair. Under that engine, the existing E61-selected policy completed E67 with **255/2,560 Heart wins (9.9609%)** and zero execution faults. The preassigned roles contain 156/1,536 fit wins, 46/512 label-holdout wins, and 53/512 development wins. All 2,560 terminal states/RNG, 347,087 outside-NN choices, and fresh replans of all 255 winners passed verification. Nine Act-3-without-Heart endings remain failures. This is the repaired-engine source baseline, not a new trained model result.

The user authorized publishing the work and pursuing a 50% win-rate target. Acceptance means at least 512 Heart wins on 1,024 seed families outside all training, tuning, and model selection, with a frozen model/runtime, confidence interval, explicit execution failures, and full replay verification. E67's assigned families are development material and cannot serve as that final test. Original-game parity and simulator win rate remain separate claims.

## Current experiments

**E69 is collecting 6,324 full continuations.** For every eligible fit or label-holdout family, it tries all first-boss relic choices, including a newly planned parent-choice control. It will compare 23 learned relic scores with a public-state neural ranker containing 92,407 trainable parameters. Both use exactly 1,000 updates on the same labels; the surrounding policy and combat engine are frozen. A candidate needs at least ten net wins and paired exact p<.05 at both the heldout-choice and 512-natural-development gates, plus all integrity checks. The E69 runtime and protocol remain frozen while collection runs.

**E70 is waiting for E69.** The user proposed combining relic and card-selection strategies. A registered 128-family fit-only pilot will enumerate the first boss relic and the last remaining card offer after the first Act 2 battle. Earlier Prayer Wheel offers retain parent control. All other decisions use the E67 policy. Its hindsight comparisons measure interaction coverage, not learned win rates. Progression requires 16 mixed card states from eight families and at least four extra salvageable families beyond relic-only hindsight. Early failures remain in the denominator; no outcome-based replacements are allowed.

**E71 is registered and waiting for E70's coverage gate.** If that gate passes, expand to all E69 fit/label-holdout relic branches, reusing audited pilot leaves. Train relic-only, card-only, and joint arms for exactly 2,000 updates. The joint objective marginalizes true terminal outcomes across the two decisions; the first decision never receives the future card offer. Fit-only option support, a frozen base policy, and all 1,536 assigned fit families define training. Full-data coverage must include 64 mixed card families and 30 extra salvageable families beyond relic-only hindsight. A failed coverage gate ends the experiment without optimizer updates.

E71 compares against the E69-selected incumbent if it passed complete development, otherwise against the E67 parent. Heldout and 512-natural-development gates each require ten net wins, paired exact p<.05, zero faults, all NN/terminal/RNG checks, and fresh winner replans. Three-arm selection is development, not unseen acceptance. E71 protocol SHA is `9a1c963581efa845842a9e72cf85410d447caef1c19605602cb2683fb7fd457b`. Its complete data preparation, formal training, and development have not run. Main simulation pools are sequential and use eight single-thread workers.

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
