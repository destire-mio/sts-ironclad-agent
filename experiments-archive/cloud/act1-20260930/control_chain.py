import time,subprocess,sys,json
from pathlib import Path
O=Path(__file__).resolve().parent
while '"done": true' not in (O/'extract.log').read_text():time.sleep(5)
subprocess.run([sys.executable,str(O/'profile.py')],check=True)
# A single controller uses two workers, sharing the same four-core affinity as every task.
subprocess.run([sys.executable,str(O/'budget.py'),'budget-control-plan.json','2'],check=True)
