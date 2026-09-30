import os,sys,pathlib,json,gzip,hashlib
os.environ['OMP_NUM_THREADS']=os.environ['OPENBLAS_NUM_THREADS']='1';sys.dont_write_bytecode=True
root=pathlib.Path(__file__).resolve().parents[1];parent=pathlib.Path(sys.argv[1]).resolve();inputs=pathlib.Path(sys.argv[2]).resolve()
os.environ['P300_RUNTIME']=str(parent/'runtime-delivery');sys.path[:0]=[str(parent/'agent'),str(root/'evidence/io-q')]
import p300_common as C
import paired_io as IO
out=root/(sys.argv[3] if len(sys.argv)>3 else 'inputs');out.mkdir(exist_ok=True);rows=json.loads((inputs/'fixed-states.json').read_text())['rows']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
records=[]
for i,row in enumerate(rows):
 p=inputs/'traj'/row['file'];assert sha(p)==row['sha256'];run=json.loads(gzip.decompress(p.read_bytes()));g=C.sts.GameContext(C.sts.CharacterClass.IRONCLAD,run['seed'],20)
 for n,step in enumerate(run['prefix']):
  C.H.clock_input(g,C.CONFIG)
  if n==row['index']:break
  if step['kind']=='battle':
   b=C.sts.BattleContext();b.init(g)
   for bits in step['actions']:
    a=C.sts.SearchAction.from_bits(bits&0xffffffff);assert a.is_valid(b);a.execute(b)
   assert int(b.outcome)==step['outcome'];b.exit_battle(g)
  else:
   a=C.sts.GameAction(step['action']&0xffffffff);assert a.is_valid(g);a.execute(g)
 assert step['kind']=='battle'
 if 'state' in row:assert C.H.fingerprint(g)==row['state']['fingerprint'],i
 s=IO.dump(g,True);clone=IO.load(s)
 assert IO.dump(g)==IO.dump(clone),(i,'roundtrip')
 # Independently validate the continuation against the original callback with a saved plan.
 b1=C.sts.BattleContext();b1.init(g);b2=C.sts.BattleContext();b2.init(clone)
 for bits in step['actions']:
  a=C.sts.SearchAction.from_bits(bits&0xffffffff);assert a.is_valid(b1) and a.is_valid(b2);a.execute(b1);a.execute(b2)
 b1.exit_battle(g);b2.exit_battle(clone);assert IO.dump(g)==IO.dump(clone),(i,'callback replay drift')
 p=out/f'{i:04}.json';p.write_text(s)
 entry=json.loads(s);records.append(dict(position=i,case=row,sha256=sha(p),feed=any(c['id']==int(C.sts.CardId.FEED) for c in entry['deck']['cards'])))
 if i%50==0:print(i,flush=True)
(out/'manifest.json').write_text(json.dumps(dict(source_sha256=sha(inputs/'fixed-states.json'),count=len(rows),rows=records,protocol='Exact q pre-battle fields, all 14 full RNG streams, deck/relic internal counts and map; original vs imported saved-plan exit including real callback checked for every row. Inactive selection/shop state excluded.'),indent=2))
print(json.dumps({'states':len(records),'feed_states':sum(x['feed'] for x in records),'callback_roundtrips':len(records)}))
