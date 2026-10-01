# Documentation index

Start with the repository [README](../README.md) for what the project is and how to run it.
This page is the map for everything under `docs/`.

## Current status and orientation

| File | What it covers |
|---|---|
| [status-2026-09-30.md](status-2026-09-30.md) | Snapshot of results, the adopted teacher, and rejected experiments |
| [history.md](history.md) · [history.zh-CN.md](history.zh-CN.md) | Chronological project history |
| [journey.md](journey.md) | Narrative of the research direction |
| [ironclad-training-status.md](ironclad-training-status.md) | Training/acceptance-status notes |
| [evaluation.md](evaluation.md) | Evaluation rules and how numbers are produced |
| [first-principles-plan.md](first-principles-plan.md) | Design rationale for the decision layer and combat search |
| [training-lessons.md](training-lessons.md) | Distillation lessons learned |
| [ironclad-experiments.md](ironclad-experiments.md) · [ironclad-research-direction-review.md](ironclad-research-direction-review.md) | Experiment index and research-direction review |
| [fullrun-windows.md](fullrun-windows.md) | Windows full-run notes |

## Original-game validation and the live bridge

| File | What it covers |
|---|---|
| [live-original-distill3-student-20261001.md](live-original-distill3-student-20261001.md) (+ `.json`) | Real-game validation of the third distilled student (merged batch, 50.1%) |
| [live-original-runbook.md](live-original-runbook.md) | How to run the original-game evaluation |
| [live-original-20-runs-20260927.md](live-original-20-runs-20260927.md) (+ `.json`) | First 20 original-game runs and simulator comparison |
| [live-original-foundation-20260928.md](live-original-foundation-20260928.md) (+ `.json`) | Bridge foundation checks (state comparison, RNG, load/save) |
| [live-original-rng-fix-20260927.md](live-original-rng-fix-20260927.md) · [live-original-rng-gate-20260927.md](live-original-rng-gate-20260927.md) | Special RNG sources and the RNG parity gate |
| [live-original-search-entry-20260927.md](live-original-search-entry-20260927.md) (+ `.json`) | Search-entry checks and evidence |
| [live-original-source-manifest.json](live-original-source-manifest.json) · [live-original-search-imports.json](live-original-search-imports.json) | Source/import manifests |

## Bridge repairs

| File | What it covers |
|---|---|
| [original-importer-repairs-2026-10-01.md](original-importer-repairs-2026-10-01.md) (+ `.json`) | Queue-import and event-continuation repairs (the first 32 faults) |
| [original-importer-followup-2026-10-01.md](original-importer-followup-2026-10-01.md) (+ `.json`) | Follow-up review: frozen-runtime mismatch, Pen Nib queue/counters |

## Research

| File | What it covers |
|---|---|
| [p300-fight-decomposition.md](p300-fight-decomposition.md) | P300 fight decomposition and value tables |
| [acknowledgements.md](acknowledgements.md) | Credits and third-party components |

## Experiment records

[`experiments/`](experiments/) holds the per-experiment records (sources, configs and result notes for each numbered experiment). These are the raw trail behind the summaries above; read them only when you need a specific experiment.
