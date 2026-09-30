from common import *
import time,traceback
from concurrent.futures import ProcessPoolExecutor,as_completed

def one(j):
 r=dict(job=j,error=None,arms=[])
 try:
  g,original=restore(j['seed'],j['index']);assert g.screen_state==S.ScreenState.BATTLE
  r.update(before=E.snap(g),rng=dict(g.rng_states),fingerprint=C.H.fingerprint(g))
  for scale in (1,4):
   cp=C.F.copy_game(g);assert dict(cp.rng_states)==dict(g.rng_states);assert C.H.fingerprint(cp)==C.H.fingerprint(g)
   cpu=time.process_time();wall=time.monotonic()
   z=C.F.resolve_combat4r(cp,40000*scale,12.0)
   rr=dict(scale=scale,won=cp.outcome!=S.GameOutcome.PLAYER_LOSS,hp=int(cp.cur_hp),max_hp=int(cp.max_hp),potions=[E.potion(p) for p in cp.potions],potion_count=int(cp.potion_count),cpu=time.process_time()-cpu,wall=time.monotonic()-wall,simulations=z['simulations'],actions=[int(a) for a in z['actions']],outcome=int(z['outcome']))
   # Execute the returned legal actions from the original state, then compare terminal RNG.
   audit=C.F.copy_game(g);step(audit,dict(kind='battle',actions=rr['actions'],outcome=rr['outcome']))
   assert C.H.fingerprint(audit)==C.H.fingerprint(cp),'solver/replay mismatch'
   assert dict(audit.rng_states)==dict(cp.rng_states),'solver/replay RNG mismatch'
   rr['legal']=True
   if scale==1:
    rr['baseline_equal']=rr['actions']==original['prefix'][j['index']]['actions']
    assert rr['baseline_equal'],'N changed baseline actions'
   r['arms'].append(rr)
 except Exception:r['error']=traceback.format_exc()
 return r
if __name__=='__main__':
 plan=O/sys.argv[1];jobs=json.loads(plan.read_text());out=O/(plan.stem+'-results.jsonl')
 with out.open('x') as f,ProcessPoolExecutor(max_workers=int(sys.argv[2])) as pool:
  for fu in as_completed([pool.submit(one,j) for j in jobs]):
   r=fu.result();f.write(json.dumps(r)+'\n');f.flush()
   print(json.dumps(dict(seed=r['job']['seed'],error=r['error'],arms=[{k:v for k,v in a.items() if k not in ('actions',)} for a in r['arms']])),flush=True)
