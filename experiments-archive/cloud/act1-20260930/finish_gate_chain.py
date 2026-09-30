import subprocess,time,json,sys
from pathlib import Path
O=Path(__file__).resolve().parent
while True:
 try:
  gate=[json.loads(l) for l in (O/'gate-results.jsonl').read_text().splitlines()]
  if len(gate)==3:
   assert not any(g['error'] for g in gate),gate
   break
 except FileNotFoundError:pass
 time.sleep(5)
for p in ['route_audit.py','potion_audit.py']:
 subprocess.run([sys.executable,str(O/p)],check=True)
