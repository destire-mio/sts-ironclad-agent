# Real Steam bridge

Current P300 combat integration: `prepare_live_runtime.py`, `live_battle.py`,
and `live_search.py` run the frozen sims32/boss12/reuse policy from an original
BattleContext and record every executed command and comparison. See
`docs/live-original-search-entry-20260927.md` and the runbook. This is a bounded
first-battle entry; the legacy outside-policy adapter below does not encode the
current P300 parent network and is not a full-arm evaluation entry.

This adapter drives the real Steam game through CommunicationMod:

- Arm G or a random baseline handles non-combat choices.
- Both groups use the same exact-state MCTS combat search.
- `state_export_mod/` adds `full_rng_state` to every in-game decision: all 13
  dungeon RNGs, Neow's RNG, MathUtils and Collections, including initialization
  state and inherited Gaussian caches. All 64-bit values use decimal strings.
- The legacy six-stream `combat_state.rngs` and energy-per-turn fields remain
  compatible with the combat importer.
- `steam_mcts.py` rebuilds a simulator `BattleContext` and maps its action back to a
  CommunicationMod command.

## Prerequisites

1. Slay the Spire, ModTheSpire, BaseMod, and CommunicationMod.
2. `sts_lightspeed` checked out at the commit documented in `sim_patch/`.
3. Apply `sim_patch/sim_rl_hooks.patch` and build the Python module.
4. Install Python dependencies used by the training code (`torch`; `tensorboard` only
   for training).

## Setup

```bash
cp .env.example .env
# edit STS_LIGHTSPEED_BUILD and optional game paths

cd steam/state_export_mod
./build.sh
```

Point CommunicationMod's external-process command at:

```text
/absolute/path/to/sts-rl-agent/steam/run_live_bridge.sh
```

Then launch the modded game. Runtime JSONL files are written under `runs/` by default
and are ignored by Git.

## Evidence boundary

The learned network does not choose combat cards. Combat is online MCTS planning.
The real-Steam adapter is an integration and sim-to-real validation layer; aggregate
performance numbers come from the controlled simulator evaluation.

The new RNG export does not implement complete game-state reconstruction or
save/load recovery. See `docs/live-original-rng-fix-20260927.md` for the bounded
original-Java validation and `docs/live-original-runbook.md` for the probe entry.
