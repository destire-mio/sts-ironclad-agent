# One low-priority supervisor. No writes outside this task directory.
import subprocess,time,json,sys,os
from pathlib import Path
O=Path(__file__).resolve().parent
while True:
 try:
  good='"done": true' in (O/'extract.log').read_text()
  gate=[json.loads(l) for l in (O/'gate-results.jsonl').read_text().splitlines()]
  if good and len(gate)==3:
   assert not any(g['error'] for g in gate),gate
   break
 except FileNotFoundError:pass
 time.sleep(5)
subprocess.run([sys.executable,str(O/'make_plan.py')],check=True)
subprocess.run([sys.executable,str(O/'suffix_worker.py'),'outer-plan.json','4'],check=True)
