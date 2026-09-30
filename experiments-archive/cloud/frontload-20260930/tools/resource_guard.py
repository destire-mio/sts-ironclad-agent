"""Suspend only this experiment's workers when external reservations consume all CPUs."""
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import time
ROOT=Path(__file__).resolve().parents[1]
paused={}

def owned_workers():
    processes={}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:
            argv=(path/'cmdline').read_bytes().split(b'\0')
            if b'tools/run_whole.py' not in argv or (path/'cwd').resolve()!=ROOT:continue
            status=(path/'stat').read_text().split()
            processes[int(path.name)]=(int(status[3]),status[21])
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    return {pid:start for pid,(parent,start) in processes.items() if parent in processes}

with (ROOT/'whole/resource-pauses.jsonl').open('a') as log:
    while True:
        workers=owned_workers()
        ledger=ROOT/'whole/resource-ledger.jsonl'
        with ledger.open('rb') as h:
            h.seek(max(0,ledger.stat().st_size-12000));row=json.loads(h.read().splitlines()[-1])
        if row['reserved_external']>=64:
            for pid,start in workers.items():
                if paused.get(pid)==start:continue
                try:os.kill(pid,signal.SIGSTOP)
                except ProcessLookupError:continue
                paused[pid]=start
                log.write(json.dumps(dict(time=datetime.now().isoformat(),action='stop_owned_worker',pid=pid,
                                          start=start,reserved_external=row['reserved_external']))+'\n');log.flush()
        elif row['reserved_external']<=60:
            for pid,start in list(paused.items()):
                if workers.get(pid)==start:
                    try:os.kill(pid,signal.SIGCONT)
                    except ProcessLookupError:pass
                    log.write(json.dumps(dict(time=datetime.now().isoformat(),action='continue_owned_worker',pid=pid,
                                              start=start,reserved_external=row['reserved_external']))+'\n');log.flush()
                paused.pop(pid,None)
        if not workers and not paused and '"event": "complete", "pairs": 2000' in (ROOT/'whole.log').read_text():break
        time.sleep(5)
