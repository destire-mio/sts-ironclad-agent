import sys,json,math,gzip
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
sys.path.insert(0,str(Path('agent').resolve()))
import heart_whole_policy_gradient as G
root=Path(__file__).parent;plan=G.E.read(root/'protocol.json');source=Path(plan['source']);rows=[];stats=defaultdict(lambda:dict(states=0,chosen_nonparent=0,alternatives=0,rare_alternatives=0,almost_parent=0,parent_probabilities=[],entropy=[]))
for i in range(128):
 for j in range(4):
  run=G.E.read(source/f'learning/round-0/episodes/{i}-{j}.json.gz')
  assert run['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
  for row in run['policy_samples']:
   if len(row['active'])<2:continue
   kinds=[]
   for f in row['features']:
    one=[k for k,v in f if k<24 and v==1.];assert len(one)==1;kinds.append(one[0])
   parentpos=row['active'].index(row['parent']);kind=kinds[parentpos];p=np.asarray(row['probabilities']);s=stats[kind]
   s['states']+=1;s['chosen_nonparent']+=int(row['chosen']!=row['parent']);s['parent_probabilities'].append(float(p[parentpos]));s['almost_parent']+=int(p[parentpos]>1-1e-6)
   alts=np.delete(p,parentpos);s['alternatives']+=len(alts);s['rare_alternatives']+=int((alts<1e-6).sum());s['entropy'].append(float(-(p[p>0]*np.log(p[p>0])).sum()))
for k,s in stats.items():
 for name in ('parent_probabilities','entropy'):
  x=s.pop(name);s[name+'_mean']=float(np.mean(x));s[name+'_median']=float(np.median(x))
report=dict(status='complete',source=str(source),games=512,families=128,states=sum(s['states'] for s in stats.values()),stats=dict(stats),new_games=0,new_training_updates=0,limits='Observed initial-policy visited menus; alternative probabilities below one in a million indicate low conditional exposure, not counterfactual action benefits. No changed recipe or additional sampling authorized by this metric alone.')
(root/'exploration-review.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
