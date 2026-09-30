import sys,json,gzip,math,time
from pathlib import Path
import torch
sys.path.insert(0,str(Path('agent').resolve()))
import heart_whole_policy_gradient as G
root=Path(__file__).parent; plan=G.E.read(root/'protocol.json');x=G.C.D.runtime(plan['runtime']);p=G.Policy(x,temperature=1.)
rows=[];seen=set();started=time.monotonic()
for family in G.E.read(root/'result.json')['families']:
 for arm,winner in family['selected'].items():
  key=(family['seed'],winner['id'])
  if not winner['win'] or not winner['changes'] or key in seen:continue
  seen.add(key);record=G.E.read(root/'families'/str(key[0])/(key[1]+'.json.gz'));run=record['run']
  changes={c['index']:c for c in record['changes']};gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,key[0],20);log_prefix=0.
  for i,step in enumerate(run['prefix']):
   x.R.clock_input(gc,x.config)
   if step['kind']=='outside':
    actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc)
    features,scores,active,parent,probs=p.menu(gc,x.A.obs_vec(gc),actions,ds)
    pos=[int(a.bits) for a in actions].index(step['action']);where=[j for j,v in enumerate(active) if v==pos];chance=float(probs[where[0]]) if where else 0.
    if i in changes:
     rows.append(dict(seed=key[0],candidate=key[1],index=i,act=int(gc.act),floor=int(gc.floor_num),kind=int(x.R.kind(ds[pos])),legal=True,in_active=bool(where),conditional_probability=chance,log_exact_prefix_probability=log_prefix,parent_probability=float(probs[list(active).index(parent)]),action_count=len(actions),active_count=len(active),state_fingerprint_matches=x.R.fingerprint(gc)==step['before']))
    log_prefix+=math.log(chance) if chance else -math.inf
   x.R.replay_step(gc,step,x.config)
  x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
report=dict(status='complete',routes=len(seen),interventions=len(rows),all_supported=all(r['in_active'] for r in rows),minimum_conditional_probability=min(r['conditional_probability'] for r in rows),maximum_conditional_probability=max(r['conditional_probability'] for r in rows),rows=rows,seconds=time.monotonic()-started,new_planning_games=0,limits='Selected hindsight winners only. Conditional action probabilities and exact-prefix likelihood do not estimate chance of finding any successful route or expected action advantage. Native action replay; no new MCTS.')
(root/'support-review.json').write_text(json.dumps(report,indent=2,allow_nan=False))
print(json.dumps(report,indent=2))
