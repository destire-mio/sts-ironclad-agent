# Experiment archive

Reports and results from runs that are otherwise excluded from git (`runs/`, ~36 GB local, ~52 GB cloud).
Only text summaries, scripts and small JSON were kept; raw per-game data, model weights (`.pt`, `.npz`),
native binaries and per-item files were left out. Absolute machine paths were rewritten
(`<repo-parent>`, `~`), so hashes recorded inside a few JSON files no longer match their files.

- `local-runs/` — P200–P212, P300 fight decomposition, Heart research (2026-09-24 to 09-29).
  For P210/P211 only top-level summaries are kept, not the ~14,000 per-battle records.
- `cloud/` — cloud experiments c5–c52 (2026-09-2x to 09-30): per-game results as `cNN-*.jsonl.gz`
  (one JSON line per game), logs, launch scripts (`q*.sh`, `kq*.sh`), analysis scripts
  (`pair.py` paired comparison, `dec_an.py` decision forks), and small outputs of the act-1 analysis,
  front-load, loss and distillation runs.

Reports written during the project are in `docs/reports/`.
