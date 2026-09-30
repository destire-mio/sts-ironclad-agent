import os,sys,pathlib,json,time,hashlib,traceback
os.environ['OMP_NUM_THREADS']=os.environ['OPENBLAS_NUM_THREADS']='1';sys.dont_write_bytecode=True
root=pathlib.Path(__file__).resolve().parents[1]
mode=sys.argv[1];parent=pathlib.Path(sys.argv[2]).resolve();worker=int(sys.argv[3]);workers=int(sys.argv[4])
runtime=(parent if mode=='q' else root)/'runtime-delivery'
os.environ['P300_RUNTIME']=str(runtime);sys.path[:0]=[str(root/'agent'),str(root/'evidence'/('io-'+mode))]
import p300_common as C
import paired_io as IO
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
input_dir=root/os.environ.get('COMBAT4R_INPUT_SET','inputs');manifest=json.loads((input_dir/'manifest.json').read_text());out=root/'evidence'/os.environ.get('COMBAT4R_RESULT_SET','fixed');out.mkdir(exist_ok=True)
import fcntl
group_lock=(out/f'group-{mode}-{worker}-{workers}.lock').open('a');fcntl.flock(group_lock,fcntl.LOCK_EX)
fn=getattr(C.F,'resolve_combat4'+mode)
repeat=set(x['position'] for x in manifest['rows'] if x['feed'])|set(range(8))
identity={'manifest_sha256':sha(input_dir/'manifest.json'),'engine_sha256':sha(pathlib.Path(C.sts.__file__)),'fightsim_sha256':sha(pathlib.Path(C.F.__file__)),'io_sha256':sha(pathlib.Path(IO.__file__))}
(out/f'identity-{mode}-{worker}.json').write_text(json.dumps(identity,indent=2))
def replay(g,res):
 b=C.sts.BattleContext();b.init(g);feeds=0;feed_plays=0;maxhp_gain=0
 for bits in res['actions']:
  a=C.sts.SearchAction.from_bits(bits&0xffffffff)
  assert int(b.outcome)==0 and a.is_valid(b),('illegal',bits)
  isfeed=int(a.action_type)==0 and b.hand[a.source_idx].id==C.sts.CardId.FEED
  hp=int(b.player.max_hp);a.execute(b)
  if isfeed:feed_plays+=1;feeds+=int(b.player.max_hp)>hp;maxhp_gain+=int(b.player.max_hp)-hp
 rng=dict(b.rng_states);assert int(b.outcome)==res['outcome'];b.exit_battle(g)
 return dict(feeds=feeds,feed_plays=feed_plays,feed_maxhp=maxhp_gain,battle_rng=rng)
for x in manifest['rows']:
 i=x['position']
 if i%workers!=worker:continue
 dest=out/f'{i:04}-{mode}.json'
 if dest.exists():
  prior=json.loads(dest.read_text())
  if prior.get('error') is not None or 'replay' not in prior:raise RuntimeError('failed/incomplete prior primary '+str(dest))
  continue
 row=dict(position=i,mode=mode,case=x['case'],error=None)
 try:
  p=input_dir/f'{i:04}.json';assert sha(p)==x['sha256'];s=p.read_text();g=IO.load(s);before=IO.dump(g)
  # The r-only state defaults to the reference BaseMod shuffle mode.
  entry=json.loads(before);original=json.loads(s);original.pop('continuation');entry.pop('endTurnShuffle',None);assert entry==original
  start=time.process_time();wall=time.perf_counter();res=dict(fn(g,x['case']['sims'],12.0));cpu=time.process_time()-start;wall=time.perf_counter()-wall
  after=IO.dump(g);row.update(result=res,cpu=cpu,wall=wall,after=json.loads(after));dest.write_text(json.dumps(row,indent=2));copy=IO.load(s);detail=replay(copy,res);assert IO.dump(copy)==after,'postcombat replay mismatch'
  row.update(result=res,cpu=cpu,wall=wall,after=json.loads(after),win=res['outcome']==1,feed=x['feed'],replay=detail)
  if mode=='r' and i in repeat:
   duplicate=IO.load(s);again=dict(fn(duplicate,x['case']['sims'],12.0));assert again==res and IO.dump(duplicate)==after,'nondeterminism';row['deterministic']=True
 except Exception:row['error']=traceback.format_exc()
 dest.write_text(json.dumps(row,indent=2));print(json.dumps({'i':i,'mode':mode,'error':row['error'],'hp':row.get('after',{}).get('curHp')}),flush=True)
