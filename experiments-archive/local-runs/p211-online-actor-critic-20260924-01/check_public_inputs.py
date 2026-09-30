"""Read-only representation checks on P203's existing conflicting inputs."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import torch

sys.path.insert(0,str(Path('agent').resolve()))
import heart_online_actor_critic as P
import heart_whole_policy_gradient as G

root=Path(__file__).resolve().parent
plan=P.checked(root);spec=P.E.read(root/'feature-spec.json')
x=P.C.D.runtime(plan['runtime']);torch.set_num_threads(1)
old=G.Policy(x)
initial=torch.load(root/'learning/initial.pt',weights_only=True,map_location='cpu')
new=P.Policy(x,spec,initial['actor_state'],0)
source=root.parent/'p203-information-audit-20260924-01'
groups=P.E.read(source/'collision-result.json')['conflict_groups']
previous=P.E.read(source/'public-context-result.json')['groups']

def inputs(gc,action):
    before=x.R.fingerprint(gc)
    actions=list(x.R.sts.get_legal_game_actions(gc));_,descriptors,_=x.A.build_choices(gc)
    obs=x.A.obs_vec(gc);legacy,_,active,parent,_=old.menu(gc,obs,actions,descriptors)
    row,new_parent,_,features=new.menu(gc,obs,actions,descriptors)
    candidate=[int(a.bits) for a in actions].index(action)
    assert parent==new_parent and before==x.R.fingerprint(gc)
    pair=legacy[[list(active).index(parent),list(active).index(candidate)]].numpy()
    new_pair=features[[parent,candidate]]
    return dict(old_digest=hashlib.sha256(pair.tobytes()).hexdigest(),
        actor_digest=hashlib.sha256(new_pair.tobytes()).hexdigest(),
        state_digest=P.digest(P.state_features(row,spec))),features,obs

reports=[]
for group,expected in zip(groups,previous,strict=True):
    members=[]
    for row,prior in zip(group,expected,strict=True):
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,row['seed'],20)
        encoded,_,_=inputs(gc,row['action'])
        assert encoded['old_digest']==prior['pair_digest'] and row['seed']==prior['seed']
        members.append(dict(seed=row['seed'],action=row['action'],**encoded))
    reports.append(dict(rows=len(members),old_unique=len({r['old_digest'] for r in members}),
        actor_unique=len({r['actor_digest'] for r in members}),
        state_unique=len({r['state_digest'] for r in members}),members=members))

row=groups[0][0];gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,row['seed'],20)
a,fa,oa=inputs(gc,row['action']);original=str(gc.boss)
gc.boss=x.R.sts.MonsterEncounter.SLIME_BOSS
b,fb,ob=inputs(gc,row['action'])
sensitivity=dict(original_boss=original,changed_boss=str(gc.boss),
    old_equal=a['old_digest']==b['old_digest'],actor_equal=np.array_equal(fa,fb),
    state_equal=a['state_digest']==b['state_digest'],
    observation_changed_columns=[i for i,(u,v) in enumerate(zip(oa,ob)) if u!=v])
assert all(r['old_unique']==1 and r['actor_unique']==r['rows'] and r['state_unique']==r['rows'] for r in reports)
assert sensitivity['old_equal'] and not sensitivity['actor_equal'] and not sensitivity['state_equal']
result=dict(status='passed',groups=reports,boss_sensitivity=sensitivity,
    new_planning_calls=0,new_training_updates=0,candidate_changed=False,
    hashes={str(p):P.E.sha(p) for p in (Path(__file__).resolve(),source/'collision-result.json',source/'public-context-result.json')},
    limits='Existing outcome-conflict cases, not an unbiased population. Reinitializes native contexts and checks observable input equality only. Synthetic boss alteration has no continuation or training label. Does not establish action-value accuracy, learning benefit or policy win rate.')
P.put(root/'public-input-check.json',result)
print(dict(status='passed',groups=[{k:v for k,v in r.items() if k!='members'} for r in reports],
    boss_sensitivity=sensitivity,new_planning_calls=0,new_training_updates=0))
