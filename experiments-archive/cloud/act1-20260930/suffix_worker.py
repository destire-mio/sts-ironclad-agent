from common import *
import time,traceback
from concurrent.futures import ProcessPoolExecutor,as_completed
SV._TABLES=json.loads((O/'stage-tables.json').read_text())
def one(j):
 r=dict(job=j,error=None)
 try:
  g,rawr=restore(j['seed'],j['index']);assert rawr['prefix'][j['index']]['action']==j['before_bits']
  r.update(before=E.snap(g),rng=dict(g.rng_states),fingerprint=C.H.fingerprint(g))
  g0=C.F.copy_game(g);assert C.H.fingerprint(g0)==C.H.fingerprint(g);assert dict(g0.rng_states)==dict(g.rng_states)
  # Original full-game suffix is a validated deterministic cache.
  for z in rawr['prefix'][j['index']:]:step(g0,z)
  assert all(rawr[k]==v for k,v in dict(status=C.H.terminal(g0),hp=int(g0.cur_hp),max_hp=int(g0.max_hp),floor=int(g0.floor_num),act=int(g0.act)).items())
  r['control']={k:rawr[k] for k in ('status','win','act','floor','hp','max_hp','error')};r['control']['legal_replay']=True
  cp=C.F.copy_game(g);assert dict(cp.rng_states)==r['rng'];post=[]
  for bit in j['after_plan']:
   a=S.GameAction(bit&0xffffffff);assert a.is_valid(cp),('illegal alternative',bit,E.snap(cp));a.execute(cp);post.append(E.snap(cp));C.H.clock_input(cp,C.CONFIG)
  r['after_decision']=post
  dest=O/'continuations'/j['id'];dest.mkdir(parents=True)
  cpu=time.process_time();wall=time.monotonic();rr=P.play(j['seed'],rawr['arm'],[101,102,103,104],500,str(dest),start=cp)
  rr.update(cpu=time.process_time()-cpu,wall=time.monotonic()-wall);rr.pop('end_features',None)
  assert not rr['error'],rr
  assert rr['status'] in ('death','heart_win','act3_without_heart'),rr['status']
  traj=json.load(gzip.open(next(dest.glob('*.json.gz')),'rt'));audit=C.F.copy_game(cp)
  for z in traj['prefix']:step(audit,z)
  assert C.H.terminal(audit)==rr['status'] and int(audit.cur_hp)==rr['hp'],'suffix mismatch'
  rr['legal_replay']=True;r['alternative']=rr
  r['rescued']=not rawr['win'] and rr['win'];r['lost']=rawr['win'] and not rr['win']
  r['act1_rescued']=rawr['act']==1 and rr['act']>1
  r['act1_lost']=rawr['act']>1 and rr['act']==1
 except Exception:r['error']=traceback.format_exc()
 return r
if __name__=='__main__':
 plan=O/sys.argv[1];jobs=json.loads(plan.read_text());dest=O/(plan.stem+'-results.jsonl')
 assert len(json.loads((O/'gate-plan.json').read_text()))==3
 gates=list(map(json.loads,(O/'gate-results.jsonl').read_text().splitlines()));assert len(gates)==3 and not any(g['error'] for g in gates),'gate incomplete'
 with dest.open('x') as out,ProcessPoolExecutor(max_workers=int(sys.argv[2])) as pool:
  for fu in as_completed([pool.submit(one,j) for j in jobs if not j.get('shared_with')]):
   r=fu.result();out.write(json.dumps(r)+'\n');out.flush();print(json.dumps({k:r.get(k) for k in ('job','error','rescued','lost','act1_rescued','act1_lost')}),flush=True)
