#!/bin/sh
# Play games with the adopted teacher (p300_play_v21) on a fixed seed block.
#   scripts/run_teacher.sh [GAMES] [WORKERS] [FIRST_SEED] [OUTPUT]
# Results: one JSON line per game in OUTPUT (default runs/teacher.jsonl). Re-running resumes.
set -e
cd "$(dirname "$0")/.."
GAMES=${1:-4}
WORKERS=${2:-4}
FIRST_SEED=${3:-3900012000}
OUTPUT=${4:-runs/teacher.jsonl}
ARMS='sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4'
mkdir -p "$(dirname "$OUTPUT")"
cd agent
../.venv/bin/python p300_play_v21.py "../$OUTPUT" --arms "$ARMS" --first-seed "$FIRST_SEED" --games "$GAMES" --workers "$WORKERS"
../.venv/bin/python - "../$OUTPUT" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
wins = sum(r['win'] for r in rows)
faults = sum(1 for r in rows if r.get('error'))
print(f"{len(rows)} games, {wins} Heart wins ({100*wins/max(len(rows),1):.1f}%), {faults} engine faults")
PY
