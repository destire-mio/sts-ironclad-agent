# Ironclad A20 training status

Scope: Ironclad, Ascension 20, natural start through the Heart, including three keys, two Act 3 bosses, and Act 4. Prismatic Shard is excluded. Combat uses MCTS; a neural policy controls out-of-combat decisions.

The latest frozen simulator evaluation E61 scored 121/1024 Heart wins (11.8164%) on a second independent seed set. This is a simulator result, not an original-game win rate. E62 replayed those 121 saved winning routes in the original game and found a first divergence on each route; execution stopped at that point, so those replays do not establish original-game wins or losses.

E64 repairs four additional differences found in E63: Necronomicon autoplay, zero-damage Thorns, acquisition-ordered card-use relic hooks, and the 999 player-block cap. A fixed 39-case original-game fixture improved from 28 matches/11 mismatches to 39 matches. The full local CTest suite passed 150 checks. The portable patch build passed five native cases and the 39-case replay test. These checks do not close E62's remaining rule/RNG discrepancies or the original-game full-run parity gap. Exhaust-animation cost reset timing remains an explicit diagnostic.

The user authorized the next phase on 2026-09-18: publish the current work and pursue a 50% win-rate target. Acceptance means at least 512 Heart wins on 1024 fresh seed families that were never used for training, tuning, or model selection, with a frozen model/runtime, confidence interval, explicit execution failures, and full replay verification. Development experiments must use separate seed families and fixed budgets. Original-game parity and simulator win rate remain separate claims.

Next: repair confirmed training-relevant E62 discrepancies, freeze the repaired engine, regenerate or revalidate affected labels, establish a new development baseline, then train and evaluate successive candidates. Do not relabel historical results as results of the new engine or repeatedly rerun a rejected hypothesis. The experiment log is preserved in [ironclad-experiments.md](ironclad-experiments.md). Raw models, game JARs, binaries, and run traces remain local.

## Python validation

Historical trajectory tests require their original local run artifacts and native engines. They cannot share an interpreter with tests of a newer engine: Python caches imported native modules, and repaired rules can change an old saved trajectory. Run each module with its declared engine:

```bash
python tests/run_isolated.py --build /path/to/current/native/build --output /path/to/new/test-results
```

The runner verifies the loaded module path and archived engine hashes. On 2026-09-18, all 19 test modules passed. A prior single-process discovery run mixed runtimes and failed; those failures are retained in the local publication evidence. This historical suite requires the local `runs/` archives; the CMake rule tests and retained original-game fixtures in `sim_patch/alignment/` are the distributable regression entry points.
