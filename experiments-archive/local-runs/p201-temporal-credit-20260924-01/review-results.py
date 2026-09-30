import sys,json,gzip,hashlib,math
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path('agent').resolve()))
import heart_whole_policy_gradient as G
root=Path(__file__).parent;plan=G.E.read(root/'protocol.json');claimed=G.E.read(root/'result.json');source=Path(plan['source']);roles=G.E.read(source/'roles-private.json');training=G.E.read(root/'learning/completion.json')
assert claimed['status']=='complete'
wins={};used={};steps=0;choices=0;replans=0
for arm in ('grouped','state_mc','temporal'):
 wins[arm]=[]
 path=root/'learning'/(arm+'.pt');assert G.E.sha(path)==training['reports'][arm]['checkpoint_sha256'];used[str(path)]=G.E.sha(path)
 for i,seed in enumerate(roles['evaluation']):
  path=root/f'evaluation/{arm}/{i}.json.gz';r=G.E.read(path);used[str(path)]=G.E.sha(path)
  assert r['seed']==seed and r['arm']==arm and r['checkpoint_sha256']==training['reports'][arm]['checkpoint_sha256'] and r['sampling_seed']==G.stream_seed('evaluation',i,0,0)
  assert not r.get('error') and r['status'] in ('heart_win','death','act3_without_heart')
  assert r['audit']['public_inputs_sampling_state_rng_and_terminal_verified'] and r['audit']['maximum_probability_error']<1e-10
  steps+=len(r['prefix']);choices+=r['audit']['outside_choices'];wins[arm].append(int(r['status']=='heart_win'))
  if wins[arm][-1]:
   path=root/f'evaluation/{arm}/replan-{i}.json.gz';repeat=G.E.read(path);used[str(path)]=G.E.sha(path)
   assert r['winner_replanned'] and repeat['status']=='heart_win' and repeat['prefix']==r['prefix'] and repeat['terminal_fingerprint']==r['terminal_fingerprint']
   assert repeat['audit']['public_inputs_sampling_state_rng_and_terminal_verified'];replans+=1
controls=[]
for i,seed in enumerate(roles['evaluation'][:2]):
 path=root/f'evaluation/initial_control/{i}.json.gz';r=G.E.read(path);old=G.E.read(source/f'learning/evaluation/initial/{i}-0.json.gz');used[str(path)]=G.E.sha(path)
 assert r['seed']==seed and r['prefix']==old['prefix'] and r['terminal_fingerprint']==old['terminal_fingerprint'];controls.append(r['status'])
 if r['status']=='heart_win':
  rp=root/f'evaluation/initial_control/replan-{i}.json.gz';rr=G.E.read(rp);used[str(rp)]=G.E.sha(rp);assert rr['prefix']==r['prefix'] and rr['terminal_fingerprint']==r['terminal_fingerprint'];replans+=1
index_path=Path(G.E.read(source/'protocol.json')['natural_source'])/'fit-references.json'
refs={r['seed']:r for r in G.E.read(index_path)};used[str(index_path)]=G.E.sha(index_path);parent=[]
for seed in roles['evaluation']:
 ref=refs[seed];assert G.E.sha(ref['path'])==ref['sha256'];raw=G.E.read(ref['path']);used[ref['path']]=ref['sha256']
 assert raw['seed']==seed and raw['status']==ref['status'] and not raw.get('error');parent.append(int(raw['status']=='heart_win'))
def pair(a,b):
 gain=sum(not x and y for x,y in zip(a,b));loss=sum(x and not y for x,y in zip(a,b));n=gain+loss
 return dict(gained=gain,lost=loss,net_gain=gain-loss,exact_p=min(1.,2*sum(math.comb(n,i) for i in range(min(gain,loss)+1))/(2**n)))
pairs={a:dict(grouped=pair(wins['grouped'],v),parent=pair(parent,v)) for a,v in wins.items() if a!='grouped'}
for arm,bs in pairs.items():
 for b,r in bs.items():
  c=claimed['comparisons'][arm][b];assert r['net_gain']==c['net_gain'] and abs(r['exact_p']-c['exact_p'])<1e-12
assert {k:sum(v) for k,v in wins.items()}==claimed['wins'] and sum(parent)==claimed['parent_wins'] and replans==claimed['winner_replans']
report=dict(status='reviewed',families=128,base_games=386,wins={k:sum(v) for k,v in wins.items()},parent_wins=sum(parent),replans=replans,steps=steps,choices=choices,comparisons=pairs,temporal_vs_state=pair(wins['state_mc'],wins['temporal']),faults=0,hashes=used,limits='Raw artifact and arithmetic reconciliation. Original worker native state/RNG and independent NumPy probability audits inherited, not reexecuted by this review. Historical development only.')
(root/'artifact-review.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='hashes'},indent=2))
