"""Exactly eight fresh fix5 smoke runs; output must not already exist."""
import json
import os
import subprocess
from pathlib import Path

O = Path(__file__).resolve().parent
root = Path.home() / 'sts'
assert json.loads((O / 'deployment-validation.json').read_text())['error'] is None
out = O / 'smoke-fix5.jsonl'
with out.open('x'):
    pass
arm = 'sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4+traj+fix5'
env = dict(os.environ, P300_RUNTIME=str(root / 'combat4r/runtime-delivery'),
           PYTHONPATH=str(root / 'principles/agent'), PYTHONDONTWRITEBYTECODE='1',
           OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
cmd = [str(root / 'venv/bin/python'), str(root / 'principles/agent/p300_play_v22.py'),
       str(out), '--arms', arm, '--games', '8', '--first-seed', '3900012000',
       '--workers', '4', '--record-dir', str(O / 'smoke-traj')]
with (O / 'smoke-command.json').open('x') as handle:
    json.dump(dict(command=cmd, affinity=sorted(os.sched_getaffinity(0)), nice=os.getpriority(os.PRIO_PROCESS, 0)), handle, indent=2)
assert os.sched_getaffinity(0) <= {0, 1, 2, 3}
assert os.getpriority(os.PRIO_PROCESS, 0) >= 10
subprocess.run(cmd, env=env, check=True)
rows = [json.loads(line) for line in out.read_text().splitlines()]
assert len(rows) == 8 and {r['seed'] for r in rows} == set(range(3900012000, 3900012008))
assert all(r['error'] is None and 'fix5' in r and 'fix5_log' in r for r in rows)
print(json.dumps(dict(n=len(rows), errors=0, wins=sum(r['win'] for r in rows),
                      fix5=sum(sum(r['fix5'].values()) for r in rows)), indent=2), flush=True)
