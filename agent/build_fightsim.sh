#!/bin/sh
# Build agent/fightsim.cpp into build/ against the frozen E121 engine core used by production runs.
set -e
PROV=/Users/destire/Documents/ChatGPT/sljt/ironclad-alignment/evidence/e121-power-order-repair-20260920-01
VENV=/Users/destire/Documents/Codex/2026-09-10/new-chat-2/outputs/spire-lab/.venv
HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/../build"
mkdir -p "$OUT"
/usr/bin/c++ -std=c++17 -O2 -arch arm64 -fPIC -fvisibility=hidden -bundle -undefined dynamic_lookup -flto \
  -I$PROV/source/include -I$VENV/lib/python3.12/site-packages/pybind11/include \
  -I/opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/include/python3.12 \
  "$HERE/fightsim.cpp" $PROV/build/libsts_core.a -o "$OUT/fightsim.tmp.so" && mv "$OUT/fightsim.tmp.so" "$OUT/fightsim.cpython-312-darwin.so"
