# Ironclad A20 training status

Scope: Ironclad, Ascension 20, natural start through the Heart, including three keys, two Act 3 bosses, and Act 4. Prismatic Shard is excluded. Combat uses MCTS; a neural policy controls out-of-combat decisions.

The latest frozen simulator evaluation E61 scored 121/1024 Heart wins (11.8164%) on a second independent seed set. This is a simulator result, not an original-game win rate. E62 replayed those 121 saved winning routes in the original game and found a first divergence on each route; execution stopped at that point, so those replays do not establish original-game wins or losses.

E64 repairs four additional differences found in E63: Necronomicon autoplay, zero-damage Thorns, acquisition-ordered card-use relic hooks, and the 999 player-block cap. A fixed 39-case original-game fixture improved from 28 matches/11 mismatches to 39 matches. The full local CTest suite passed 150 checks. The portable patch build passed five native cases and the 39-case replay test. These checks do not close E62's remaining rule/RNG discrepancies or the original-game full-run parity gap. Exhaust-animation cost reset timing remains an explicit diagnostic.

The user authorized the next phase on 2026-09-18: publish the current work and pursue a 50% win-rate target. Acceptance means at least 512 Heart wins on 1024 fresh seed families that were never used for training, tuning, or model selection, with a frozen model/runtime, confidence interval, explicit execution failures, and full replay verification. Development experiments must use separate seed families and fixed budgets. Original-game parity and simulator win rate remain separate claims.

E66 closed the confirmed training-relevant E62 rule/RNG discrepancies and froze the repaired engine. E67 is collecting new labels and a development baseline before the next model update. Do not relabel historical results as results of the new engine or repeatedly rerun a rejected hypothesis. The experiment log is preserved in [ironclad-experiments.md](ironclad-experiments.md). Raw models, game JARs, binaries, and run traces remain local.

## Python validation

Historical trajectory tests require their original local run artifacts and native engines. They cannot share an interpreter with tests of a newer engine: Python caches imported native modules, and repaired rules can change an old saved trajectory. Run each module with its declared engine:

```bash
python tests/run_isolated.py --build /path/to/current/native/build --output /path/to/new/test-results
```

The runner verifies the loaded module path and archived engine hashes. On 2026-09-18, all 19 test modules passed. A prior single-process discovery run mixed runtimes and failed; those failures are retained in the local publication evidence. This historical suite requires the local `runs/` archives; the CMake rule tests and retained original-game fixtures in `sim_patch/alignment/` are the distributable regression entry points.

## E66 and the next collection

E66 repaired 20 E62 game-rule/RNG classes and the production potion-target bridge. Twelve recorded original-game action boundaries and eight natural-prefix boundaries now match. The 161-case CTest suite passed; ten new native groups fail on the prior source and pass after repair. The standalone patch build passed 12 focused entry points. Five potion bridge tests pass, including two that fail on the old bridge. Exhaust-animation timing remains the E64 diagnostic; E68 subsequently verified four full natural same-action original-game routes, with the scope limits below.

E67 has started recollecting 2,560 fresh seed families with this engine and the previous selected policy: 1,536 fit, 512 label holdout, 512 development. Roles are fixed before collection. Old-engine outcomes are excluded as training labels. Every terminal is replayed and every winner is replanned. Execution faults retain null labels and block training. These seeds become development material and cannot serve as the final unseen 50-percent test.

## E68 original-game route checks and E69 learning

Four preselected E67 development winners matched natural original-game replays through A20 Heart victory after fixing split-slime target mapping and waiting for the original exhaust-animation callback. All 4,080 commands retained state/RNG checks; no state import or resynchronization was used. Initial failed attempts remain in the local evidence. This is four same-action trace checks, not a representative original-game win rate, live online model deployment or exhaustive parity. The comparison boundary is after rule-bearing animation callbacks settle. See [the compact evidence report](../sim_patch/alignment/e68-natural-parity-report.json).

E69 is registered and waits for the E67 full-data audit. It compares a 23-score relic ranking and a public-state neural ranker with 92,407 trainable parameters on the same complete first-boss continuations. The surrounding selected policy and combat engine are frozen. Both use exactly 1,000 optimizer updates and separate fit, label-holdout and natural-development roles. The new model's initial behavior matches a known source route under fresh NN/MCTS planning; this is an integration check, not a new win-rate result.

The E67 development cohort has generated 53 Heart wins among 512 assigned seeds (10.3516%). The complete batch and independent audits remain in progress; no new model performance or 50-percent acceptance is claimed.

The E68/E69 Python regression run covered 22 modules and 124 tests. An archived portal-trace test initially ran against the repaired engine and failed on its old RNG prefix; it passed with its declared historical engine, and the runner now assigns that engine to both portal-fixture modules. The initial failure and focused rerun are preserved. These historical fixtures do not validate old labels under the repaired engine.


## E70 joint relic and card pilot

The user requested combining relic and card-selection strategies. A registered128-family fit-only pilot will enumerate both the first boss relic and the final card offer after the first Act2 battle, while retaining the E67 policy for the remainder. It waits for E69 to finish and its label audit to pass, keeping the eight-worker resource boundary. Original choices are replanned controls; all terminal states/RNG and every other NN action are audited. Its hindsight oracle comparisons measure interaction coverage, not learned or unseen win rates. A larger joint-learning experiment requires16 mixed card states from8 families and at least4 additional salvageable families beyond relic-only hindsight. No joint optimizer updates have run.

Six new joint-policy checks and six existing contextual-relic regressions pass. A known-seed native integration reproduces the parent route with zero new scores and validates two changed-decision continuations. In that case, changing the relic while retaining the card loses; changing the subsequent card wins. The original policy already won that seed, so this is a scope/continuation contract and interaction example, not a new rescued seed or performance result.

E67 completed2560 assigned natural terminals and347087 outside-NN choice checks with zero execution faults. All255 Heart wins reproduced under fresh NN/MCTS planning. Fit/label-holdout/development have156/1536,46/512 and53/512 Heart wins; nine Act3-without-Heart endings are failures. The255/2560 (9.9609%) result is the repaired-engine old-policy source baseline. E69 verified completion and entered branch preparation. Training and final50percent acceptance remain separate stages.
