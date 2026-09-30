#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LIVE_PYTHON=${LIVE_PYTHON:-python}
exec "$LIVE_PYTHON" "$HERE/live4/cli.py" "$@"
