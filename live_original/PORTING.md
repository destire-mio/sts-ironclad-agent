# Original-game runner: status and what to adapt

当前 importer 修复位于 [`steam/`](../steam/) 与配套核心源码，见 [修复报告](../docs/original-importer-repairs-2026-10-01.md)。本目录保留采集时的脚本副本；采用修复时需要新建运行包，编译匹配扩展并刷新源码和运行包哈希。

These are the scripts Codex used to run the teacher and the student inside the real Slay the Spire
(`run.sh` -> `live4/cli.py`), copied as they were run, with local absolute paths replaced by placeholders.
The README in this directory is the original runbook (Chinese).

Not included (too large, machine-specific): the derived runtime with the live-repair engine
(`live4/runtime/`), per-seed evidence and results, the game itself, the jar and saves.

To use them you must:
1. Own the game and install ModTheSpire, BaseMod, CommunicationMod and the state-export mod (`steam/state_export_mod/`).
2. Point `LIVE_PYTHON` at a Python with torch, and adjust the path constants at the top of `runner.py`
   and `live4/*.py` (`OLD`, `RUNTIME`, the p300 agent directory). They still reflect the original layout.
3. Use the repository's `runtime/` (see the main README) in place of `live4/runtime/`. It does not contain the
   later Time Eater end-turn draw-order repair described in the runbook, so results can differ.

Nothing here was re-run after the move into this repository.
