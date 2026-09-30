#!/bin/sh
# One-time setup: Python environment + engine build + runtime identity files.
# Needs Python 3.12 (or another version, used consistently), cmake and a C++17 compiler.
set -e
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3.12}
[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet numpy torch pybind11
.venv/bin/python scripts/assemble_runtime.py --jobs "${JOBS:-8}"
echo "setup done. Try: scripts/run_teacher.sh"
