import sys,json,hashlib
from pathlib import Path
import torch
sys.path.insert(0,str(Path('agent').resolve()))
import heart_counterfactual_gain as L
root=Path('runs/p202-support-interventions-20260924-01').resolve();x=L.G.C.D.runtime(L.E.read(root/'protocol.json')['runtime']);p=L.G.Policy(x)
rows=L.E.read(Path(__file__).with_name('collision-result.json'))['conflict_groups'];reports=[]
def inputs(gc):
 actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
 f,score,active,parent,prob=p.menu(gc,obs,actions,ds)
 return obs,f,score,active,parent,prob,ds,actions
for group in rows:
 members=[]
 for row in group:
  gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,row['seed'],20);before=x.R.fingerprint(gc)
  obs,f,score,active,parent,prob,ds,actions=inputs(gc)
  assert before==x.R.fingerprint(gc)
  pos=[int(a.bits) for a in actions].index(row['action']);pair=torch.stack((f[list(active).index(parent)],f[list(active).index(pos)]))
  members.append(dict(seed=row['seed'],delta=row['delta'],boss=str(gc.boss),map_digest=hashlib.sha256(json.dumps(gc.get_map_nn()).encode()).hexdigest(),pair_digest=hashlib.sha256(pair.numpy().tobytes()).hexdigest(),neow_options=gc.neow_options))
 assert len({r['pair_digest'] for r in members})==1
 reports.append(members)
gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,rows[0][0]['seed'],20);a=inputs(gc);before_rng=str(gc)
original=str(gc.boss);gc.boss=x.R.sts.MonsterEncounter.SLIME_BOSS if original!='MonsterEncounter.SLIME_BOSS' else x.R.sts.MonsterEncounter.HEXAGHOST
b=inputs(gc)
change=dict(original_boss=original,substituted_boss=str(gc.boss),observation_changed_columns=[i for i,(u,v) in enumerate(zip(a[0],b[0])) if u!=v],network_features_equal=torch.equal(a[1],b[1]),base_scores_equal=bool((a[2]==b[2]).all()),parent_choice_equal=a[4]==b[4],limit='Synthetic public-field sensitivity check only. No game continuation, return label, training example or evaluation score produced from modified state.')
result=dict(status='complete',groups=reports,boss_sensitivity=change,new_games=0,new_training_updates=0,limits='Natural input equality and code blindness do not identify whether label variation is caused by omitted public map/boss versus hidden future randomness, nor quantify possible policy improvement.')
Path(__file__).with_name('public-context-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
