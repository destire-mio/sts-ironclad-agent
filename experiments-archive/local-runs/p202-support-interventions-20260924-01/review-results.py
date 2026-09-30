import sys,json
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path('agent').resolve()))
import heart_support_interventions as S
E=S.E;root=Path(__file__).parent;plan=S.checked(root)
claimed=E.read(root/'recovery/result.json');assert claimed['status']=='complete_recovered' and claimed['unresolved_faults']==0
roles=E.read(root/'roles-private.json');assert len(roles['fit'])==192 and len(roles['held'])==64
assert {r['seed'] for r in roles['fit']}.isdisjoint(r['seed'] for r in roles['held'])
used={};outcomes=[];family_rows=[];replans=0;steps=0;counts=Counter();by_kind={}
def read(path):
 used[str(path)]=E.sha(path);return E.read(path)
for ref in roles['fit']:
 seed=ref['seed'];original=root/'collection'/str(seed);recovery=root/'recovery/collection'/str(seed)
 report=read(recovery/'result.json' if (recovery/'result.json').exists() else original/'result.json')
 assert report['status'] in ('complete','complete_recovered') and report['seed']==seed
 source=read(Path(ref['path']));assert used[ref['path']]==ref['sha256'];parent_win=int(source['status']=='heart_win');assert parent_win==report['parent_win']
 roots=read(original/'menus-private.json.gz');assert len(roots)<=2 and len({m['kind'] for m in roots})==len(roots)
 assigned={(m['index'],a['action']):(m,a) for m in roots for a in m['options']}
 actual={(r['index'],r['action']):r for r in report['outcomes']};assert set(assigned)==set(actual)
 assert len(actual)==len(report['outcomes'])<=6
 family_gain=False
 for key,(menu,option) in assigned.items():
  row=actual[key];name=str(key[0])+'-'+str(key[1])+'.json.gz'
  path=Path(row['record']) if row.get('record') else original/name
  record=read(path);run=record['run'];index=key[0]
  assert option['probability']<=1e-6 and row['probability']==option['probability']==record['original_probability']
  assert run['seed']==seed and run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error')
  assert run['audit']['state_rng_terminal'] and run['prefix'][:index]==source['prefix'][:index]
  assert run['prefix'][index]==dict(kind='outside',before=menu['before'],action=key[1])
  assert source['prefix'][index]['before']==menu['before'] and source['prefix'][index]['action']==menu['parent_action']!=key[1]
  assert len(record['changes'])==1 and record['changes'][0]['index']==index and record['changes'][0]['action']==key[1]
  assert menu['active'][option['active_position']]==option['position'] and menu['parent_position'] in menu['active']
  win=int(run['status']=='heart_win');delta=win-parent_win;assert row['win']==win and row['delta']==delta
  if win:
   rp=Path(row['replan']) if row.get('replan') else original/('replan-'+name);rr=read(rp)
   assert rr['status']=='heart_win' and rr['prefix']==run['prefix'] and rr['terminal_fingerprint']==run['terminal_fingerprint'];replans+=1
   assert len(set(run['audit']['act3_bosses']))==2 and run['audit']['act4']==['SHIELD_AND_SPEAR','THE_HEART']
  family_gain|=delta>0;counts[str(delta)]+=1;steps+=len(run['prefix']);by_kind.setdefault(str(menu['kind']),Counter())[str(delta)]+=1
  outcomes.append(dict(seed=seed,index=index,action=key[1],kind=menu['kind'],act=menu['act'],floor=menu['floor'],delta=delta,record=str(path)))
 assert family_gain==bool(report['rescued'])
 family_rows.append(dict(seed=seed,parent_win=parent_win,roots=len(roots),rescued=family_gain))
rescue=sum(r['rescued'] for r in family_rows);nonzero=counts['1']+counts['-1'];assert rescue==claimed['rescued_fit_families'] and nonzero==claimed['nonzero_pairs'] and len(outcomes)==claimed['completed_suffixes']
assert sum(r['parent_win'] for r in family_rows)==claimed['parent_wins'] and claimed['gate_passed']==(rescue>=12 and nonzero>=30)
original=read(root/'result.json');attempts=read(root/'recovery/attempts.json');assert original['total_new_plans']+len(attempts)==claimed['total_new_plans']<=2308 and len(attempts)<=48
assert not any((root/'collection'/str(r['seed'])).exists() for r in roles['held'])
result=dict(status='reviewed',families=192,held_families_not_collected=64,parent_wins=claimed['parent_wins'],eligible_families=sum(r['roots']>0 for r in family_rows),rescued_fit_families=rescue,paired_returns=dict(counts),by_kind={k:dict(v) for k,v in by_kind.items()},completed_suffixes=len(outcomes),verified_winning_suffixes=replans,recorded_steps=steps,total_new_plans=claimed['total_new_plans'],historical_execution_faults=claimed['original_execution_faults'],unresolved_faults=0,gate_passed=claimed['gate_passed'],hashes=used,limits='Assignment, label, budget and raw artifact reconciliation. Native state/RNG evidence inherited from original collection and once-only winner replans; no extra native games in this review. Fitting-only teacher evidence, not policy win rate.')
(root/'artifact-review.json').write_text(json.dumps(result,indent=2));(root/'fitting-rows.json').write_text(json.dumps(outcomes,separators=(',',':')))
print(json.dumps({k:v for k,v in result.items() if k!='hashes'},indent=2))
