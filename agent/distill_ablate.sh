#!/usr/bin/env bash
# Diagnostic teacher interventions, not single-NN policies.
# Resident shell + Python controller + six workers = eight processes.
set -euo pipefail
cd "$HOME/sts/principles/agent"
export P300_RUNTIME="$HOME/sts/combat4p/runtime-delivery"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
distill_checkpoint="${1:-$HOME/sts/runs/distill-models/base192.pt}"
distill_prefix="${2:-$HOME/sts/runs/distill-eval/base-ablate16}"
for distill_kind in map card_reward card_select shop; do
  "$HOME/sts/venv/bin/python" distill_eval.py \
    --output "$distill_prefix-$distill_kind.jsonl" --models "$distill_checkpoint" \
    --first-seed 3900016000 --games 16 --workers 6 --skip-teacher --teacher-types "$distill_kind"
done
