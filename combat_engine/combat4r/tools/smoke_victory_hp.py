import os,sys,pathlib,json,hashlib,collections
os.environ['OMP_NUM_THREADS']=os.environ['OPENBLAS_NUM_THREADS']=os.environ['MKL_NUM_THREADS']='1';sys.dont_write_bytecode=True
r=pathlib.Path(__file__).resolve().parents[1];driver=pathlib.Path.home()/'sts/principles/agent/p300_play_v15.py'
os.environ['P300_RUNTIME']=str(r/'runtime-delivery');sys.path.insert(0,str(driver.parent))
import p300_play_v15 as P
arm='sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3'
seeds=list(range(3000000000,3000000008));out=r/'evidence/victory-hp/smoke.jsonl';assert not out.exists()
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
(r/'evidence/victory-hp/smoke-plan.json').write_text(json.dumps(dict(arm=arm,seeds=seeds,workers=1,entry='resolve_combat4r',driver_sha256=sha(driver),engine_sha256=sha(P.C.sts.__file__),fightsim_sha256=sha(P.C.F.__file__)),indent=2))
original=P.C.F.resolve_combat4r;calls=collections.Counter()
def measured(g,budget,boss):
 assert budget==(80000 if int(g.act)==4 else 40000) and boss==12
 calls[(int(g.act),budget,boss)]+=1
 return original(g,budget,boss)
P.C.F.resolve_combat4r=measured
with out.open('x') as f:
 for seed in seeds:
  calls.clear();row=P.play(seed,arm,[101,102,103,104],500);row['c4r_calls']=[dict(act=a,budget=b,boss_multiplier=c,count=n) for (a,b,c),n in sorted(calls.items())]
  f.write(json.dumps(row)+'\n');f.flush();print(json.dumps({k:row[k] for k in ['seed','status','error','floor']}),flush=True)
