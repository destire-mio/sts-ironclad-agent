"""Recover only missing death enemy/entry HP; no alternate-policy search."""
import os
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import sys,json,traceback,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
OUT=Path.home()/'sts/runs/losses3'
sys.path.insert(0,str(OUT/'source'))
import p300_play_v9 as P
import p300_common as C
FILES={'c23':Path.home()/'sts/runs/c23-base3.jsonl','c33':OUT/'c33-analysis.jsonl'}
def one(job):
    cohort,row=job;seed=row['seed'];log=[]
    try:
        fn='resolve_combat4p' if '+c4p' in row['arm'] else 'resolve_combat4';original=getattr(C.F,fn)
        def logged(g,sims,multiplier):
            entry=C.summary(g);entry['potions_list']=[int(p) for p in g.potions]
            result=original(g,sims,multiplier)
            log.append(dict(entry,won=g.outcome!=C.sts.GameOutcome.PLAYER_LOSS,hp_after=int(g.cur_hp)))
            return result
        setattr(C.F,fn,logged)
        try:result=P.play(seed,row['arm'],[101,102,103,104],500)
        finally:setattr(C.F,fn,original)
        keys=('status','win','act','floor','bosses','hp','max_hp','simulations','teacher_calls','teacher_changed','rest_overrides','fixes','guides')
        mismatch={k:[row.get(k),result.get(k)] for k in keys if row.get(k)!=result.get(k)}
        return {'cohort':cohort,'seed':seed,'mismatch':mismatch,'last_battle':log[-1] if log else None,'status':result['status'],'error':result['error'],'seconds':result['seconds']}
    except Exception:return {'cohort':cohort,'seed':seed,'error':traceback.format_exc()}
if __name__=='__main__':
    if sys.argv[1]=='gate':
        rows=list(map(json.loads,FILES['c23'].read_text().splitlines()))
        pool=[r for r in rows if r['status']=='death' and not any(not b['won'] for b in r['bosses'])]
        seeds=[min((r for r in pool if r['act']==a),key=lambda r:r['seed']) for a in (1,2,3,4)]
        with (OUT/'metadata-gate.jsonl').open('a') as f:
            for r in seeds:
                z=one(('c23',r));f.write(json.dumps(z)+'\n');f.flush();print(json.dumps(z),flush=True)
                if z.get('error') or z.get('mismatch'):break
    else:
        jobs=[];done=set()
        for name in ('metadata-gate.jsonl','death-metadata.jsonl'):
            p=OUT/name
            if p.exists():
                for line in p.read_text().splitlines():
                    r=json.loads(line)
                    if not r.get('error') and not r.get('mismatch'):done.add((r['cohort'],r['seed']))
        for k,fn in FILES.items():
            for r in map(json.loads,fn.read_text().splitlines()):
                if r['status']=='death' and not any(not b['won'] for b in r['bosses']) and (k,r['seed']) not in done:jobs.append((k,r))
        with (OUT/'death-metadata.jsonl').open('a') as f,ProcessPoolExecutor(max_workers=3) as pool:
            fs=[pool.submit(one,j) for j in jobs]
            for fut in as_completed(fs):
                r=fut.result();f.write(json.dumps(r)+'\n');f.flush()
                print(json.dumps({k:v for k,v in r.items() if k!='last_battle'}),flush=True)
