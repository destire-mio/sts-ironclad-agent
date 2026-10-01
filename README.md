<div align="center">

# sts-ironclad-agent

**A20 Ironclad bot for Slay the Spire: one frozen network for every out-of-combat choice, simulator search in combat — about 50% Heart win rate in the simulator and the real game.**

English | [中文](README.zh-CN.md)

</div>

Built on [sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed), continued from
[Jialeiv/sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent). The goal is an Ironclad that wins
Ascension 20 with all three keys and the Heart, where every out-of-combat choice comes from one
frozen network and only combat search stays classical.

## Results

| Game | Policy | Seeds | Games | Heart win rate | 95% interval |
|---|---|---|---:|---:|---:|
| Simulator | P300 teacher (`agent/p300_play_v21.py`) | development block | 2,000 | 50.1% | — |
| Simulator | P300 teacher | fresh block | 1,000 | 49.5% | — |
| Simulator | distilled student ([`student/`](student/README.md)) | development block 3900040000+ | 1,000 | 50.2% | — |
| **Original game** | **distilled student (v3)** | fresh block 3900020000+ | 473 | **48.8%** | [44.4, 53.5] |

- **Simulator** = fixed-seed simulation. **Original game** = real Java, A20 against the Heart, combat search retained, one frozen network for out-of-combat choices, faults listed separately.
- The original-game interval covers the simulator estimate, so this run gives **no evidence that the simulator number is inflated**.
- Evaluation rule: fixed seeds, no reseeding, no retrying, no repeated search on one decision. The locked 1,024-unseen-seed acceptance has not been run.
- Original-game report and per-game data: [`docs/live-original-distill3-student-20261001.md`](docs/live-original-distill3-student-20261001.md).

Where the losses come from (simulator, 3,000 games; death rate among games reaching each stage):

| Act 1 path | Act 1 boss | Act 2 path | Act 2 boss | Act 3 path | Act 3 bosses | Shield & Spear | Heart |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 9.1% | 1.9% | 10.3% | 5.1% | 4.3% | 9.3% | 3.7% | 21.3% |

The Heart fight is decided mainly by the deck and entry HP (90% win at ≥75% HP, 31% below 50%); more
search budget does not help. Details and rejected experiments: [`docs/status-2026-09-30.md`](docs/status-2026-09-30.md).

## How it works

1. **Decision layer** — map, card rewards, shops, campfires, events and relics are chosen by one frozen network distilled from the teacher.
2. **Combat** — simulator search (`sims32`, extra boss budget, subtree reuse); engine source in [`combat_engine/`](combat_engine/combat4r/).
3. **Evaluation** — fixed seeds only; acceptance numbers must come from unseen seeds.

## Simulator vs original game

The simulator carries patches ([`sim_patch/`](sim_patch/README.md)) and a real-game parity checker
([`sim_patch/parity/`](sim_patch/parity/README.md)). Consistency is still **`INCOMPLETE`** — the
bridge faults on some queued-action cases — so it is not a move-for-move reproduction, but the first
original-game run above agrees with the simulator within its interval. The live bridge to the real
game is kept on the `live-original-bridge` branch.

## Repository map

| Path | Contents |
|---|---|
| `agent/` | teacher drivers (`p300_play_v21.py`, `p300_play_v24.py`), distillation and Heart research tools |
| `student/` | distilled student network (weights, code, interface, `play_student.py`) |
| `live_original/` | scripts that ran the teacher/student in the real game (paths still to adapt) |
| `combat_engine/` | combat engine source and the post-battle HP scoring report |
| `runtime/` | frozen parent network, config and runtime files (engine built into `runtime/engine/`) |
| `data/` | stage value tables the teacher reads |
| `sim_patch/` | simulator patches, native alignment tests, original-game parity checker |
| `steam/` | real-game state export and live search |
| `docs/` | [status](docs/status-2026-09-30.md), [history](docs/history.md), experiment records |
| `experiments-archive/` | reports and results from P200-P212 and cloud runs c5-c52 |
| `scripts/` | `setup.sh`, `run_teacher.sh`, `assemble_runtime.py` |
| `tests/` | regression tests (need the built `slaythespire` module and PyTorch) |

## Quick start

Needs Python 3.12, `cmake` and a C++17 compiler (tested on macOS arm64). The engine source, parent
network and value tables are all in this repository.

```bash
scripts/setup.sh                 # venv + numpy/torch/pybind11, build the engine, write runtime identity files
scripts/run_teacher.sh 4 4       # 4 games on 4 workers with the adopted teacher
scripts/run_student.sh 4 4       # same, but the student network decides outside combat
```

`run_teacher.sh [GAMES] [WORKERS] [FIRST_SEED] [OUTPUT]` writes one JSON line per game and prints
the win count; a game takes about a minute on one core and runs resume. Use an unseen seed block for
an honest number (development block: `3900012000+`). A fresh CMake build does not reproduce the
cloud games move for move (the delivery used PGO/LTO), so treat its win rates as unmeasured until
re-run — see [`combat_engine/combat4r/report.md`](combat_engine/combat4r/report.md). The
original-game runner is in [`live_original/`](live_original/PORTING.md) (as run; needs your own game
and mods).

## Credits and license

- Simulator: [gamerpuppy/sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed) (MIT).
- Real-game bridge: [CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod),
  [ModTheSpire](https://github.com/kiooeht/ModTheSpire), [BaseMod](https://github.com/daviscook477/BaseMod).
- This repository: MIT, see [`LICENSE`](LICENSE) and [`docs/acknowledgements.md`](docs/acknowledgements.md).
  Slay the Spire is a trademark of Mega Crit Games; this is an unaffiliated research project.
