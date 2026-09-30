import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

root=Path(__file__).resolve().parent;repo=root.parent.parent;started=time.time()
command=[sys.executable,'-u',str(repo/'agent/heart_support_interventions.py'),'collect','--root',str(root)]
child=subprocess.Popen(command,cwd=repo,start_new_session=True)
(root/'collection-launch.json').write_text(json.dumps(dict(pid=os.getpid(),child_pid=child.pid,pgid=child.pid,
    command=command,started_at=started,timeout_seconds=5400),indent=2))
timed_out=False
try:code=child.wait(timeout=5400)
except (subprocess.TimeoutExpired,KeyboardInterrupt):
    timed_out=True;os.killpg(child.pid,signal.SIGTERM)
    try:code=child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid,signal.SIGKILL);code=child.wait()
finally:
    try:os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    (root/'collection-exit.json').write_text(json.dumps(dict(exit_code=child.returncode,timed_out=timed_out,
        elapsed_seconds=time.time()-started,ended_at=time.time()),indent=2))
sys.exit(code)
