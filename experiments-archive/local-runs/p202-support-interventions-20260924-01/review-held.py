import sys,json,math
from pathlib import Path
sys.path.insert(0,str(Path('agent').resolve()))
import heart_counterfactual_evaluation as V
root=Path(__file__).parent;plan=V.checked(root);roles=V.E.read(root/'roles-private.json');expected=V.E.read(root/'evaluation/held-result.json')
assert expected['status']=='complete';counts=dict(both_win=0,both_fail=0,gained=0,lost=0);changed=0;plans=0;steps=0;used={}
def read(path):
 used[str(path)]=V.E.sha(path);return V.E.read(path)
for ref in roles['held']:
 seed=ref['seed'];folder=root/'evaluation/held';row=read(folder/(str(seed)+'-result.json'));source=read(Path(ref['path']))
 assert used[ref['path']]==ref['sha256'] and row['status']=='complete' and row['seed']==seed
 assert row['checkpoint_sha256']==plan['checkpoint_sha256'] and row['maximum_numeric_error']<1e-10
 a=int(source['status']=='heart_win');b=row['win'];assert row['parent_win']==a;changed+=row['changed'];plans+=row['plans']
 if row['changed']:
  record=read(folder/(str(seed)+'-branch.json.gz'));run=record['run'];choice=row['selected_root'];index=choice['index']
  assert record['decision']==choice and choice['gain']>.05 and run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error')
  assert run['seed']==seed and run['prefix'][:index]==source['prefix'][:index] and run['prefix'][index]['before']==source['prefix'][index]['before']
  assert run['prefix'][index]['action']==choice['action'] and source['prefix'][index]['action']==choice['parent_action']!=choice['action']
  assert run['audit']['state_rng_terminal'] and len(record['changes'])==1 and int(run['status']=='heart_win')==b
  assert row['plans']==1+b;steps+=len(run['prefix'])
  if b:
   repeat=read(folder/(str(seed)+'-replan.json.gz'));assert repeat['prefix']==run['prefix'] and repeat['terminal_fingerprint']==run['terminal_fingerprint'] and repeat['interventions_applied']==record['changes']
 else:assert b==a and row['plans']==0
 counts['both_win' if a and b else 'both_fail' if not a and not b else 'gained' if b else 'lost']+=1
n=counts['gained']+counts['lost'];p=min(1,2*sum(math.comb(n,i) for i in range(min(counts['gained'],counts['lost'])+1))/2**n)
assert counts['gained']-counts['lost']==expected['paired']['net_gain'] and p==expected['paired']['exact_p'] and plans==expected['new_plans'] and changed==expected['changed_roots']
report=dict(status='reviewed',families=64,counts=counts,parent_wins=counts['both_win']+counts['lost'],candidate_root_wins=counts['both_win']+counts['gained'],changed_roots=changed,new_plans=plans,recorded_branch_steps=steps,exact_p=p,gate_passed=False,hashes=used,limits='One selected root per held historical family, same parent continuation. Worker public-feature/numerical checks and native state/RNG evidence inherited; artifact/return reconciliation here. No complete learned-policy natural evaluation or final unseen acceptance.')
(root/'evaluation/held-review.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='hashes'},indent=2))
