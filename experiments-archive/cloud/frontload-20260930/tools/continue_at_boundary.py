"""Switch controllers at a durable completed batch boundary without repeating games."""
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]

def original_processes():
    result={}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if b'tools/run_whole.py' in (p/'cmdline').read_bytes().split(b'\0') and (p/'cwd').resolve()==ROOT:
                result[int(p.name)]=int((p/'stat').read_text().split()[3])
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    return result

libc=ctypes.CDLL(None,use_errno=True)
fd=libc.inotify_init1(os.O_NONBLOCK)
assert fd>=0
assert libc.inotify_add_watch(fd,os.fsencode(ROOT/'whole/rows'),0x00000080)>=0  # IN_MOVED_TO
while True:
    names={p.name for p in (ROOT/'whole/rows').glob('*.json')}
    started={p.name for p in (ROOT/'whole/started').glob('*.json')}
    procs=original_processes()
    if names and len(names)%200==0 and names==started and procs:
        parents=[pid for pid,parent in procs.items() if parent not in procs]
        assert len(parents)==1
        pid=parents[0]
        record=dict(time=datetime.now().isoformat(),controller_pid=pid,completed_arms=len(names),
                    started_arms=len(started),action='SIGINT controller only at completed batch boundary',
                    worker_signals_sent=0)
        (ROOT/'evidence/controller-boundary-request.json').write_text(json.dumps(record,indent=2))
        os.kill(pid,signal.SIGINT)
        break
    assert procs, 'Original controller exited before boundary inspection.'
    select.select([fd],[],[],5)
    try:os.read(fd,65536)
    except BlockingIOError:pass
os.close(fd)
while original_processes():time.sleep(1)
print('Original controller and its workers exited; validating complete ledger.',flush=True)
proc=subprocess.Popen([sys.executable,'-u','tools/run_remaining.py'],cwd=ROOT,
                      stdout=(ROOT/'continuation.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
(ROOT/'continuation.pid').write_text(str(proc.pid)+'\n')
print(json.dumps(dict(continuation_pid=proc.pid)),flush=True)
