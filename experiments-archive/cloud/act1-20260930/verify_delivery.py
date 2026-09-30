from common import *
import importlib.util,traceback,collections,hashlib,time
from candidates import augment,match
SV._TABLES=json.loads((O/'stage-tables.json').read_text())
path=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'principles/agent/p300_play_v22.py'
spec=importlib.util.spec_from_file_location('act1_delivered_v22',path);M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
x,parent=M.runtime()
rows=[augment(json.loads(l)) for l in gzip.open(O/'act1-decisions.jsonl.gz','rt')]
selected=set(M.FIX5_RULES);jobs=[];neg=[];sample_for_log={}
for r in rows:
 for z in r['steps']:
  if z['kind']=='battle':continue
  expected={k:v for k,v in match(z).items() if k in selected}
  j=dict(seed=r['seed'],index=z['index'],arm=r['result']['arm'],chosen=z['chosen']['bits'],expected=expected)
  if expected:jobs.append(j)
  else:neg.append(j)
neg=sorted(neg,key=lambda j:hashlib.sha256(('fix5-negative-'+str(j['seed'])+'-'+str(j['index'])).encode()).hexdigest())[:100]
result=dict(source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rules=M.FIX5_RULES,positives=0,negatives=0,rule_counts={},logged=[],error=None)
counts=collections.Counter()
try:
 for j in jobs+neg:
  g,rawr=restore(j['seed'],j['index']);actions=list(S.get_legal_game_actions(g));_,desc,_=x.A.build_choices(g)
  chosen=next(i for i,a in enumerate(actions) if int(a.bits)==j['chosen'])
  fp=C.H.fingerprint(g);rng=dict(g.rng_states)
  better=M.loss_fixes5(x,g,actions,desc,chosen,parent)
  assert C.H.fingerprint(g)==fp and dict(g.rng_states)==rng,'fix5 mutated input'
  if j['expected']:
   assert len(j['expected'])==1,(j,'overlapping rules');rule,alt=next(iter(j['expected'].items()))
   assert better is not None and better[1]==rule and int(actions[better[0]].bits)==alt['bits'],(j,better)
   assert better[0]!=chosen and actions[better[0]].is_valid(g),'illegal/no-op choice'
   trial=C.F.copy_game(g);actions[better[0]].execute(trial)
   if rule=='shop_prepare_elite':
    C.H.clock_input(trial,C.CONFIG);a=S.GameAction(j['chosen']&0xffffffff);assert a.is_valid(trial),'planned shop leave illegal'
   counts[rule]+=1;result['positives']+=1;sample_for_log.setdefault(rule,j)
  else:
   assert better is None,(j,better);result['negatives']+=1
 for rule,j in sample_for_log.items():
  g,rawr=restore(j['seed'],j['index']);arm=j['arm']
  def run(a):
   calls=[0]
   def stop(_):calls[0]+=1;return calls[0]>1
   rr=M.play(j['seed'],a,[101,102,103,104],500,start=g,stop=stop)
   assert rr['error'] is None,rr
   return rr
  off=run(arm);on=run(arm+'+fix5')
  assert on['fix5'][rule]==1 and sum(on['fix5'].values())==1,(rule,on)
  assert on['fixes']==off['fixes']+1,(rule,off,on)
  log=on['fix5_log'];assert len(log)==1 and log[0]['before']==j['chosen'] and log[0]['after']==j['expected'][rule]['bits'],log
  result['logged'].append(dict(rule=rule,seed=j['seed'],index=j['index'],entry=log[0],fixes_off=off['fixes'],fixes_on=on['fixes']))
 result['rule_counts']=dict(counts)
 result['loaded_sources']={}
 for name,mod in list(sys.modules.items()):
  filename=getattr(mod,'__file__',None)
  if filename and Path(filename).parent==O/'source' and Path(filename).suffix=='.py':
   result['loaded_sources'][Path(filename).name]=hashlib.sha256(Path(filename).read_bytes()).hexdigest()
except Exception:result['error']=traceback.format_exc()
(O/(sys.argv[2] if len(sys.argv)>2 else 'delivery-validation.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2),flush=True)
assert result['error'] is None
