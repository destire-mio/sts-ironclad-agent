#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export P300_RUNTIME="$HOME/sts/combat4r/runtime-delivery"
export PYTHONPATH="$HOME/sts/principles/agent"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
exec nice -n 10 "$HOME/sts/venv/bin/python" distill2_pipeline.py "$@"
