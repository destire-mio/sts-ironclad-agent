from pathlib import Path
import copy,hashlib,importlib.util,json,sys
import numpy as np
import torch
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'program'))
import heart_whole_policy_gradient as G
E=G.E;torch.set_num_threads(1)
plan=G.registered(root);x=G.C.D.runtime(plan['runtime'])
spec=importlib.util.spec_from_file_location('review_original',root/'e191-review.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
source_paths=[]
for i in range(128):
 paths=[root/f'learning/round-0/episodes/{i}-{j}.json.gz' for j in range(4)]
 rows=[E.read(p) for p in paths]
 rewards=[int(v['status']=='heart_win') for v in rows]
 if 0<sum(rewards)<4:
  source_paths=paths;records=[]
  for row,reward in zip(rows,rewards,strict=True):
   advantage=(4*reward-sum(rewards))/3
   records.extend(dict(r,advantage=advantage) for r in row['policy_samples'] if len(r['active'])>1)
  break
assert source_paths
records=records[:256]
policy=G.Policy(x);values,sizes=R.materialize(records,5529);features=torch.from_numpy(values)
initial=copy.deepcopy(policy.initial).requires_grad_(False)
results={}
for label in ['production','separate_logsumexp','separate_log_softmax']:
 net=copy.deepcopy(initial).requires_grad_(True)
 residual=(net(features).flatten()-initial(features).flatten()).split(sizes)
 logits=[torch.tensor(row['base_scores'],dtype=torch.float64)+v for row,v in zip(records,residual,strict=True)]
 if label=='production':loss=G.objective(logits,records)[0]
 else:
  logs=[v-torch.logsumexp(v,0) if label=='separate_logsumexp' else torch.log_softmax(v,0) for v in logits]
  selected=torch.stack([v[r['chosen_active']] for v,r in zip(logs,records,strict=True)])
  ratio=(selected-torch.tensor([r['log_probability'] for r in records],dtype=torch.float64)).exp()
  adv=torch.tensor([r['advantage'] for r in records],dtype=torch.float64)
  clipped=ratio.clamp(.8,1.2)
  pg=-torch.minimum(ratio*adv,clipped*adv).mean()
  divergences=[]
  for log,row in zip(logs,records,strict=True):
   q=torch.tensor(row['probabilities'],dtype=torch.float64);mask=q>0
   divergences.append((q[mask]*(q[mask].log()-log[mask])).sum())
  loss=pg+.1*torch.stack(divergences).mean()
 optimizer=torch.optim.AdamW(net.parameters(),lr=G.RECIPE['learning_rate'],weight_decay=G.RECIPE['weight_decay'])
 optimizer.zero_grad(set_to_none=True);loss.backward()
 gradient=torch.cat([p.grad.flatten().clone() for p in net.parameters()])
 norm=torch.nn.utils.clip_grad_norm_(net.parameters(),1.);optimizer.step()
 weights=torch.cat([p.detach().flatten() for p in net.parameters()])
 results[label]=dict(loss=float(loss.detach()),gradient=gradient,weights=weights,norm=float(norm))
base=results['production'];summary={}
for label,row in results.items():
 summary[label]=dict(loss=row['loss'],gradient_norm=row['norm'],loss_error=abs(row['loss']-base['loss']),maximum_gradient_error=float((row['gradient']-base['gradient']).abs().max()),maximum_one_step_weight_error=float((row['weights']-base['weights']).abs().max()),exact_gradient_match=torch.equal(row['gradient'],base['gradient']),exact_weight_match=torch.equal(row['weights'],base['weights']))
result=dict(status='complete',records=len(records),comparisons=summary,discarded_probe_optimizer_updates=3,new_games=0,training_candidate_changed=False,source_hashes={str(p):E.sha(p) for p in source_paths},source_candidate_sha256=E.sha(root/'learning/candidate.pt'),script_sha256=E.sha(__file__),limits='A local numeric probe of one existing mixed-family batch, not a policy or success-rate result. Full independent optimizer replay remains required at the unchanged1e-9 tolerance.')
E.write(root/'probability-kernel-diagnosis.json',result);print(result,flush=True)
