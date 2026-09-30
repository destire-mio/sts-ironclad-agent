import os,sys,pathlib,json,time,hashlib,traceback,fcntl
os.environ['OMP_NUM_THREADS']=os.environ['OPENBLAS_NUM_THREADS']=os.environ['MKL_NUM_THREADS']='1';sys.dont_write_bytecode=True
r=pathlib.Path(__file__).resolve().parents[1];worker=int(sys.argv[1]);dataset=sys.argv[2] if len(sys.argv)>2 else 'fixed';inputs='inputs' if dataset=='fixed' else 'feed-inputs'
sys.path[:0]=[str(r/'runtime-delivery/engine'),str(r/'evidence/io-r')]
import slaythespire as sts
import fightsim as F
import paired_io as IO
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((r/inputs/'manifest.json').read_text());out=r/'evidence/victory-hp'/dataset;out.mkdir(parents=True,exist_ok=True)
plan=json.loads((r/'evidence/victory-hp/plan.json').read_text());assert plan['runtime_identity']==json.loads((r/'runtime-delivery/identity.json').read_text())
identity={'input_manifest_sha256':sha(r/inputs/'manifest.json'),'engine_sha256':sha(pathlib.Path(sts.__file__)),'fightsim_sha256':sha(pathlib.Path(F.__file__)),'io_sha256':sha(pathlib.Path(IO.__file__))}
assert identity['engine_sha256']==plan['runtime_identity']['engine_sha256'] and identity['fightsim_sha256']==plan['runtime_identity']['fightsim_sha256']
(out/f'identity-r-{worker}.json').write_text(json.dumps(identity,indent=2))
old=r/'revisions/pre-victory-hp'/dataset
rows=sorted(manifest['rows'],key=lambda x:plan['order'][dataset].index(x['position']))
repeat=set(x['position'] for x in manifest['rows'] if x['feed'])|set(range(8))
def replay(text,res):
 g=IO.load(text);b=sts.BattleContext();b.init(g);initial_max=int(b.player.max_hp)
 for bits in res['actions']:
  action=sts.SearchAction.from_bits(bits&0xffffffff);assert int(b.outcome)==0 and action.is_valid(b),('illegal',bits)
  action.execute(b)
 assert int(b.outcome)==res['outcome'];metrics=json.loads(IO.terminal_metrics(g,b,initial_max));rng=dict(b.rng_states)
 if metrics['victory']:assert metrics['projected_hp']==metrics['settled_hp']
 b.exit_battle(g)
 return IO.dump(g),dict(battle_rng=rng,terminal=metrics)
for x in rows:
 i=x['position'];dest=out/f'{i:04}-r.json';lock=(out/f'{i:04}.lock').open('a')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:lock.close();continue
 try:
  if dest.exists():
   prior=json.loads(dest.read_text());assert prior.get('error') is None and 'replay' in prior,'incomplete prior primary';continue
  row=dict(position=i,mode='r',case=x['case'],feed=x['feed'],error=None)
  try:
   p=r/inputs/f'{i:04}.json';assert sha(p)==x['sha256'];text=p.read_text();g=IO.load(text)
   oldrow=json.loads((old/f'{i:04}-r.json').read_text());oldafter,oldreplay=replay(text,oldrow['result']);assert json.loads(oldafter)==oldrow['after'],'previous 4r settlement changed'
   row['previous_4r_replay']=oldreplay
   start=time.process_time();wall=time.perf_counter();res=dict(F.resolve_combat4r(g,x['case']['sims'],12.0));cpu=time.process_time()-start;wall=time.perf_counter()-wall;after=IO.dump(g)
   row.update(result=res,cpu=cpu,wall=wall,after=json.loads(after),win=res['outcome']==1);dest.write_text(json.dumps(row,indent=2))
   replay_after,detail=replay(text,res);assert replay_after==after,'postcombat replay mismatch';row['replay']=detail
   before=oldreplay['terminal'];now=detail['terminal'];delta_old=now['score_before_hp_projection']-before['score_before_hp_projection'];delta_new=now['score_after_hp_projection']-before['score_after_hp_projection'];sign=lambda n:0 if abs(n)<1e-7 else (1 if n>0 else -1)
   comparable=before['victory'] and now['victory']
   row['hp_ranking']=dict(comparable_wins=comparable,old_objective_delta=delta_old,new_objective_delta=delta_new,strict_reversal=comparable and sign(delta_old)*sign(delta_new)<0,tie_order_change=comparable and sign(delta_old)!=sign(delta_new) and sign(delta_old)*sign(delta_new)==0,actions_changed=oldrow['result']['actions']!=res['actions'])
   if i in repeat:
    duplicate=IO.load(text);again=dict(F.resolve_combat4r(duplicate,x['case']['sims'],12.0));assert again==res and IO.dump(duplicate)==after,'nondeterminism';row['deterministic']=True
  except Exception:row['error']=traceback.format_exc()
  dest.write_text(json.dumps(row,indent=2));print(json.dumps({'i':i,'error':row['error'],'hp':row.get('after',{}).get('curHp')}),flush=True)
 finally:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
