import json,gzip,hashlib,collections,sys
from pathlib import Path
from candidates import *
O=Path(__file__).resolve().parent
rows=[augment(json.loads(l)) for l in gzip.open(O/'act1-decisions.jsonl.gz','rt')]
assert len(rows)==2000 and not any(r['error'] for r in rows)
by=collections.defaultdict(list)
for r in rows:
 seen=set();result=r['result'];stratum='heart_win' if result['win'] else 'a1_nonboss' if result['act']==1 and result['floor']<16 else 'other_loss'
 for z in r['steps']:
  for rule,alt in match(z).items():
   if rule in seen:continue
   seen.add(rule)
   by[rule].append(dict(id=f'{rule}-{r["seed"]}-{z["index"]}',seed=r['seed'],index=z['index'],rule=rule,stratum=stratum,before_bits=z['chosen']['bits'],after_bits=alt['bits'],after_plan=[alt['bits'],z['chosen']['bits']] if rule=='shop_prepare_elite' else [alt['bits']],floor=z['before']['floor'],hp=z['before']['hp'],max_hp=z['before']['max_hp']))
selected=[];stats={};used={}
for rule in RULES:
 ls=by[rule];st={}
 for group in ('a1_nonboss','other_loss','heart_win'):
  group_ls=[j for j in ls if j['stratum']==group]
  chosen=sorted(group_ls,key=lambda j:hashlib.sha256(('act1-fix5-'+rule+'-'+str(j['seed'])).encode()).hexdigest())[:8]
  st[group]=dict(N=len(group_ls),n=len(chosen))
  for j in chosen:
   key=(j['seed'],j['index'])
   if key in used:
    assert used[key]['after_plan']==j['after_plan'],('two alternatives at same root',j,used[key])
    j['shared_with']=used[key]['id']
   else:used[key]=j
   selected.append(j)
 stats[rule]=dict(description=RULES[rule],triggers=len(ls),rate=len(ls)/2000,strata=st)
(O/'candidate-roots.json').write_text(json.dumps(by,indent=2))
(O/'outer-plan.json').write_text(json.dumps(selected,indent=2))
(O/'candidate-counts.json').write_text(json.dumps(stats,indent=2))
print(json.dumps(stats,indent=2));print('jobs',len(selected))
