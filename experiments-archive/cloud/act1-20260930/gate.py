from common import *
import time,traceback
# Freeze the small stage tables and manifest their input files before any suffix searches.
tables=SV.tables();(O/'stage-tables.json').write_text(json.dumps(tables))
(O/'stage-inputs.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in SV.RUNS.glob('*') if p.is_file() and p.name in {f for f,_ in SV.SOURCES.values()}},indent=2))
with (O/'gate-results.jsonl').open('x') as f:
 for j in json.loads((O/'gate-plan.json').read_text()):
  rr=dict(job=j,error=None)
  try:
   g,r=restore(j['seed'],j['index']);step(g,r['prefix'][j['index']]);dest=O/'gate-traj'/str(j['seed']);dest.mkdir(parents=True)
   t=time.process_time();x=P.play(j['seed'],r['arm'],[101,102,103,104],500,str(dest),start=g)
   assert not x['error'],x
   tr=json.load(gzip.open(next(dest.glob('*.gz')),'rt'))
   rr.update(cpu=time.process_time()-t,result=x,prefix_equal=tr['prefix']==r['prefix'][j['index']+1:])
   rr['first_difference']=next((k for k,(a,b) in enumerate(zip(tr['prefix'],r['prefix'][j['index']+1:])) if a!=b),None)
   rr['terminal_equal']=all(x[k]==r[k] for k in ('status','act','floor','hp','max_hp'))
   assert rr['prefix_equal'] and rr['terminal_equal'],'control divergence'
  except Exception:rr['error']=traceback.format_exc()
  f.write(json.dumps(rr)+'\n');f.flush();print(json.dumps(rr),flush=True)
