#!/usr/bin/env bash
# Cloud paired development evaluation, exactly one controller + seven workers.
# Usage: bash ~/sts/principles/agent/distill_run.sh [output.jsonl] [games]
set -euo pipefail
cd "$HOME/sts/principles/agent"
export P300_RUNTIME="$HOME/sts/combat4p/runtime-delivery"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
distill_output="${1:-$HOME/sts/runs/distill-eval/paired2000.jsonl}"
distill_games="${2:-2000}"
"$HOME/sts/venv/bin/python" distill_verify.py \
  --reference "$HOME/sts/runs/distill-eval/teacher64.manifest.json" \
  --selected "$HOME/sts/runs/distill-models/selected.json" \
  --checkpoint "$HOME/sts/runs/distill-models/selected.pt"
exec "$HOME/sts/venv/bin/python" distill_eval.py \
  --output "$distill_output" --models "$HOME/sts/runs/distill-models/selected.pt" \
  --first-seed 3900016000 --games "$distill_games" --workers 7 --no-shadow
