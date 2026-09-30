#!/bin/sh
# Play games with the frozen student network (distill2) making every out-of-combat decision.
#   scripts/run_student.sh [GAMES] [WORKERS] [FIRST_SEED] [OUTPUT]
# Combat is still simulator search. Results: one JSON line per game (default runs/student.jsonl).
set -e
cd "$(dirname "$0")/.."
GAMES=${1:-4}
WORKERS=${2:-4}
FIRST_SEED=${3:-3900040000}
OUTPUT=${4:-runs/student.jsonl}
mkdir -p "$(dirname "$OUTPUT")"
.venv/bin/python student/play_student.py "$OUTPUT" --games "$GAMES" --workers "$WORKERS" --first-seed "$FIRST_SEED"
.venv/bin/python - "$OUTPUT" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
wins = sum(bool(r.get('win')) for r in rows)
faults = sum(1 for r in rows if r.get('error'))
print(f"{len(rows)} games, {wins} Heart wins ({100*wins/max(len(rows),1):.1f}%), {faults} engine faults")
PY
