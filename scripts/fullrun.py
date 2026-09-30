"""Portable CLI. Resolves the native module built by bootstrap_fullrun.py."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
runtime = ROOT / '.runtime/runtime.json'
if not runtime.exists():
    raise SystemExit('Build the simulator first: python scripts/bootstrap_fullrun.py --test')
identity = json.loads(runtime.read_text(encoding='utf-8'))
module = Path(identity['module'])
if not module.is_file():
    raise SystemExit('Native build moved/missing. Re-run bootstrap_fullrun.py in this clone.')
os.environ['STS_LIGHTSPEED_BUILD'] = str(module.parent)
for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[variable] = '1'
sys.path.insert(0, str(ROOT / 'agent'))

if __name__ == '__main__':
    from heart_fullrun_train import main
    main()
