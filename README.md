<div align="center">

# sts-ironclad-agent

**A20 Ironclad bot for Slay the Spire: decision rules plus simulator combat search, about 50% on Heart runs.**

English | [中文](README.zh-CN.md)

</div>

Built on [sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed) and continued from
[Jialeiv/sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent). The goal is an Ironclad that wins
Ascension 20 with all three keys and the Heart, where every out-of-combat choice comes from one
frozen network and only combat search is allowed to stay classical.

## Results

| Version | Seeds | Games | Heart win rate |
|---|---|---:|---:|
| P300 teacher (`agent/p300_play_v21.py`) | development block | 2,000 | **50.1%** |
| P300 teacher | fresh block | 1,000 | **49.5%** |
| Distilled student network ([`student/`](student/README.md)) | dev block 3900040000+ | 1,000 | 50.2% (teacher 54.7% on the same seeds) |

All numbers are simulator measurements on fixed seeds, not original-game win rates. The final
1,024-unseen-seed acceptance of the distilled student network has not been run yet; its 50.2% is a development-block number.

Where the remaining losses come from (3,000 games, death rate among games reaching each stage):

| Act 1 path | Act 1 boss | Act 2 path | Act 2 boss | Act 3 path | Act 3 bosses | Shield & Spear | Heart |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 9.1% | 1.9% | 10.3% | 5.1% | 4.3% | 9.3% | 3.7% | 21.3% |

The Heart fight is decided mostly by the deck and entry HP: it is won 90% of the time at 75% HP or more,
and 31% below 50%. More search budget does not help. Details and rejected experiments are in
[`docs/status-2026-09-30.md`](docs/status-2026-09-30.md).

## How it works

1. **Decision layer.** Map, card rewards, shops, campfires, events and relics are chosen by rules and
   value tables distilled from simulator experiments; a network student is being distilled from this teacher.
2. **Combat.** Simulator search (`sims32` with extra budget on bosses, subtree reuse) plays every fight.
   The engine source is in [`combat_engine/`](combat_engine/combat4r/).
3. **Evaluation rule.** Fixed seeds only. No reseeding, no retrying and picking results, no repeated
   search on one decision, and unseen seeds for any acceptance number.

## Simulator consistency with the original game

The simulator carries patches ([`sim_patch/`](sim_patch/README.md)) and a checker that replays scenarios
in the real game ([`sim_patch/parity/`](sim_patch/parity/README.md)). Nine investigation rounds found and
repaired dozens of rule differences, but consistency is still **`INCOMPLETE`**: the simulator win rates above
do not establish the original-game win rate. A live bridge to the real game is kept on the
`live-original-bridge` branch.

## Repository map

| Path | Contents |
|---|---|
| `agent/` | bot code: teacher drivers (`p300_play_v21.py`, `p300_play_v24.py`), shared helpers, distillation and Heart research tools |
| `student/` | the distilled student network (17 MB weights, code, interface) |
| `experiments/combat_value/` | combat value-network experiment (scripts only; not part of the teacher) |
| `combat_engine/` | combat engine source snapshot and the post-battle HP scoring report |
| `runtime/` | frozen parent network, config and runtime files (the engine is built into `runtime/engine/`) |
| `data/` | stage value tables the teacher reads |
| `scripts/` | `setup.sh`, `run_teacher.sh`, `assemble_runtime.py` |
| `sim_patch/` | simulator patches, native alignment tests, original-game parity checker |
| `steam/` | real-game state export and live search |
| `experiments-archive/` | reports and results from P200-P212 and cloud runs c5-c52 |
| `docs/` | [status](docs/status-2026-09-30.md), [history](docs/history.md), 685 experiment records, lessons learned |
| `tests/` | regression tests (need the built `slaythespire` module and PyTorch) |
| `weights/` | small historical model weights |

## Quick start

Needs Python 3.12, `cmake` and a C++17 compiler (tested on macOS arm64). Everything else,
including the engine source, the parent network and the value tables, is in this repository.

```bash
scripts/setup.sh                 # venv + numpy/torch/pybind11, builds the engine, writes runtime identity files
scripts/run_teacher.sh 4 4       # play 4 games on 4 workers with the adopted teacher
```

`run_teacher.sh [GAMES] [WORKERS] [FIRST_SEED] [OUTPUT]` writes one JSON line per game and prints the win
count. A game takes roughly a minute on one core. Runs resume if you repeat the command. Use a seed block
that has not been used for tuning if you want an honest number (the development block is 3900012000+).

Verified on the last cleanup: a fresh build played seed 3900012000 to the Heart (floor 56) in 45 s
with no engine fault; the cloud teacher reached the same floor on that seed. Long-run win rates were
not re-measured with this build.

Not yet one click: the distilled student has no full-game driver in this repository (only the loading
interface, `student/INTERFACE.md`), and the original-game bridge needs your own copy of the game plus mods
([`docs/live-original-runbook.md`](docs/live-original-runbook.md)). The tests need the built engine and PyTorch.
Reproduction details for the older A0 policy are in [`docs/history.md`](docs/history.md).

## Credits and license

- Simulator: [gamerpuppy/sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed) (MIT).
- Real-game bridge: [CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod),
  [ModTheSpire](https://github.com/kiooeht/ModTheSpire), [BaseMod](https://github.com/daviscook477/BaseMod).
- This repository: MIT, see [`LICENSE`](LICENSE) and [`docs/acknowledgements.md`](docs/acknowledgements.md).
  Slay the Spire is a trademark of Mega Crit Games; this is an unaffiliated research project.
