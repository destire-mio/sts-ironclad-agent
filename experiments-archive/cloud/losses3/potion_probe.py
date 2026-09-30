"""One fixed-budget Heart search per predeclared case in an isolated runtime."""
import json,gzip,sys,time,hashlib,traceback
from pathlib import Path
O=Path.home()/'sts/runs/losses3';sys.path.insert(0,str(O/'source'))
import p300_common as C
import extract_v3 as E
from audit_events import restore
with (O/'potion-probes.jsonl').open('a') as out:
    # All four sampled deaths with a usable remaining potion, plus fixed win control.
    # Smoke Bomb at Time Eater is not usable and is excluded before testing.
    for seed in (3900012150,3900012194,3900012005,3900012212,3900012214):
        try:
            r=json.load(gzip.open(O/'replayed'/f'{seed}.json.gz','rt'))
            raw=json.load(gzip.open(next((O/'raw').glob(f'{seed}-*.json.gz')),'rt'))
            step=[s for s in r['steps'] if s['kind']=='battle'][-1]
            g=restore(raw,step['index']);before=E.snap(g);assert before==step['before']
            start=time.monotonic();result=C.F.resolve_combat4p(g,80000 if before['act']==4 else 40000,12)
            row={'seed':seed,'index':step['index'],'before':before,'control_after':step['after'],'control_search':step['search'],'after':E.snap(g),'result':result,'terminal':C.H.terminal(g),'seconds':time.monotonic()-start,'engine':str(C.sts.__file__),'engine_sha256':hashlib.sha256(Path(C.sts.__file__).read_bytes()).hexdigest()}
        except Exception:row={'seed':seed,'error':traceback.format_exc()}
        out.write(json.dumps(row)+'\n');out.flush()
        print(json.dumps({k:v for k,v in row.items() if k not in ('before','result')}),flush=True)
