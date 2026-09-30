"""Test setup: point the tests at the runtime built by scripts/assemble_runtime.py."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
os.environ.setdefault("STS_LIGHTSPEED_BUILD", str(RUNTIME / "engine"))
os.environ.setdefault("HEART_BRANCH_RUNTIME", str(RUNTIME))
for path in (RUNTIME / "engine", ROOT / "agent", RUNTIME, ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
