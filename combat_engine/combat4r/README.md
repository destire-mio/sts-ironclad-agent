# combat4r — combat engine used by the P300 teacher

Source of the combat-search engine used by `agent/p300_play_v21.py`:
optimized `sts_lightspeed` core and subtree-reuse search. The post-battle HP revision
is documented in `report.md`; the source now includes the escaped-thief value revision
`thief-gold-20261001`. Frozen experiment runtimes keep their recorded identity.

- `engine-source/` — engine sources (headers, sources, Python bindings).
- `agent/` — the `fightsim.cpp`, search-reuse header and driver files as built with this engine.
  They differ from the copies in `../../agent/`; build the engine and `fightsim` from the same snapshot.
- `build.py`, `package.py`, `tools/` — the build/packaging/audit scripts used for delivery. They
  chain to earlier delivery directories (`combat4q`) that are not in this repository, so they document
  the procedure rather than run standalone.

Not included: validation evidence, input snapshots and prebuilt binaries (about 370 MB).

## Escaped-thief value

The simulator treats Looter/Mugger escape as a surviving battle. The previous
`resolve_combat4r` score did not distinguish keeping stolen gold from losing it,
so a kill and an escape could tie even when HP and potions were identical.

The new victory score subtracts an HP-equivalent penalty for unrecovered gold.
Let `H` be HP after victory relic healing and `G` the gold carried away by escaped
thieves. If every monster escaped, add 15 to `G` for the base mean of the lost
ordinary gold reward. The penalty in HP units is `(G / 10) * H / (H + G)`.
This starts from 10 gold per HP and discounts the value at low health; the total
penalty stays below 10% of `H`. More recovery improves equal-resource plans,
including recovery from one of two thieves. For example, 40 gold can justify
2 HP at 74 HP, but does not justify 10 HP at 69 HP or 2 HP at 12 HP.

The calculation uses actual escape flags, so killing a thief on its escape turn
counts as a kill. Ectoplasm disables recovery value. The base gold estimate does
not model reward modifiers absent from `BattleContext`, and it does not roll
future rewards. Card rewards remain available after escape; potion reward odds
are not estimated. Death/escape outcomes, non-thief battles, Feed value, potion
value, search budgets and RNG behavior retain their existing rules.

Build with the repository's `scripts/assemble_runtime.py`, then run
`ctest --test-dir build/engine --output-on-failure`. The thief regression test
replays a legal Strike escape versus Headbutt kill and checks that search chooses
the kill; it also checks HP/potion tradeoffs, Ectoplasm and state/RNG preservation.
The victory-HP contract test covers the existing relic-healing behavior.

This changes finite-budget exploration as well as terminal ranking. Recovering
more gold in fixed fights does not establish a whole-run win-rate improvement.

Local validation on 2026-10-01 used identical inputs and search settings:

- 78 historical thief battle starts: escaped battles 37 -> 20; wallet plus gold
  rewards +1,016; summed post-victory HP -17; total remaining potion count unchanged.
  Every plan passed legal-action replay and full exit-state/RNG comparison.
- 12 non-thief controls: identical actions and exit states. Both CTest targets passed;
  the thief test fails against the saved pre-change core.
- 16 fixed development-seed whole-run pairs (`3900012100` through `3900012115`):
  11 Heart wins per version, with the same win/loss result in every pair and no
  execution errors. These are development seeds, not unused acceptance seeds.
- A separate diagnostic pair (`3900012003`) changed from a baseline Heart win to
  a candidate death on floor 25. Fixed-fight gains therefore do not remove the
  risk of whole-run regressions.

Adoption decision: keep this source change and its built runtime as a candidate.
The local default runtime remains `victory-hp-20260929`; the candidate runtime,
frozen baseline, inputs references, scripts and results are stored in the ignored
`runs/thief-fix-20261001/` directory. Rebuilding from this source enables the new
score, so use a separate `--runtime` directory when comparing it with the default.
