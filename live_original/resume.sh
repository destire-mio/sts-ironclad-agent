#!/bin/sh
set -eu
LIVE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LIVE_PY='python'
export PYTHONDONTWRITEBYTECODE=1
exec "$LIVE_PY" "$LIVE_DIR/batch.py" --games 100 --workers 2 --new-session "$@"
