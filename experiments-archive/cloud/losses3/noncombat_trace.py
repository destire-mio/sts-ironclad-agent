"""After the metadata queue exits, recover exact outside-combat death transitions."""
import os
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import json,gzip,sys,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
O=Path.home()/'sts/runs/losses3';sys.path.insert(0,str(O/'source'))
import p300_play_v9 as P
import p300_common as C
import extract_v3 as E
E.OUT=O/'noncombat';(E.OUT/'raw').mkdir(parents=True,exist_ok=True);(E.OUT/'replayed').mkdir(exist_ok=True)
def one(job):
    cohort,row=job;seed=row['seed']
    try:
        calls=[];fn='resolve_combat4p' if '+c4p' in row['arm'] else 'resolve_combat4';original=getattr(C.F,fn)
        def logged(g,sims,mul):
            r=original(g,sims,mul);calls.append({k:v for k,v in r.items() if k!='actions'});return r
        setattr(C.F,fn,logged)
        try:r=P.play(seed,row['arm']+'+traj',[101,102,103,104],500,str(E.OUT/'raw'))
        finally:setattr(C.F,fn,original)
        keys=('status','win','act','floor','bosses','hp','max_hp','simulations','teacher_calls','teacher_changed','rest_overrides','fixes','guides')
        mismatch={k:[row.get(k),r.get(k)] for k in keys if row.get(k)!=r.get(k)}
        path=E.OUT/'raw'/f'{seed}-{r["arm"]}.json.gz';raw=json.load(gzip.open(path,'rt'));bs=[s for s in raw['prefix'] if s['kind']=='battle'];assert len(bs)==len(calls)
        for s,c in zip(bs,calls):s['search']=c
        with gzip.open(path,'wt') as f:json.dump(raw,f)
        rr=E.one(path);full=json.load(gzip.open(E.OUT/'replayed'/f'{seed}.json.gz','rt'))
        return dict(cohort=cohort,seed=seed,mismatch=mismatch,replay_mismatch=rr.get('mismatch'),invalid=rr.get('invalid'),error=rr.get('error'),last_steps=full['steps'][-8:],terminal=full['terminal'])
    except Exception:return dict(cohort=cohort,seed=seed,error=traceback.format_exc())
if __name__=='__main__':
    rows={k:{r['seed']:r for r in map(json.loads,(O/f).read_text().splitlines())} for k,f in [('c23','c23-base3.jsonl'),('c33','c33-analysis.jsonl')]};jobs=[]
    for f in (O/'queue-results').glob('*.json'):
        if f.name.startswith('.'):continue
        r=json.loads(f.read_text())
        if r.get('queue_type')=='metadata' and not r.get('mismatch') and not r.get('error') and r['last_battle']['won']:jobs.append((r['cohort'],rows[r['cohort']][r['seed']]))
    done=set()
    summary=E.OUT/'summary.jsonl'
    if summary.exists():
        done={(r['cohort'],r['seed']) for r in map(json.loads,summary.read_text().splitlines()) if not r.get('error') and not r.get('mismatch') and not r.get('replay_mismatch') and not r.get('invalid')}
    jobs=[j for j in jobs if (j[0],j[1]['seed']) not in done]
    if '--serial' in sys.argv:
        with summary.open('a') as out:
            for j in jobs:
                r=one(j);out.write(json.dumps(r)+'\n');out.flush();print(json.dumps({k:v for k,v in r.items() if k not in ('last_steps','terminal')}),flush=True)
    else:
        with summary.open('a') as out,ProcessPoolExecutor(max_workers=3) as pool:
            for fut in as_completed([pool.submit(one,j) for j in jobs]):
                r=fut.result();out.write(json.dumps(r)+'\n');out.flush();print(json.dumps({k:v for k,v in r.items() if k not in ('last_steps','terminal')}),flush=True)
