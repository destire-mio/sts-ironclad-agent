import sys,json,hashlib
from pathlib import Path
from collections import defaultdict,Counter
sys.path.insert(0,str(Path('agent').resolve()))
import heart_counterfactual_gain as L
root=Path('runs/p202-support-interventions-20260924-01').resolve();L.checked(root)
rows=L.E.read(root/'fitting-rows.json');menus={};groups=defaultdict(list);identical=[]
for r in rows:
 seed=r['seed']
 if seed not in menus:menus[seed]={m['index']:m for m in L.E.read(root/'collection'/str(seed)/'menus-private.json.gz')}
 m=menus[seed][r['index']];a=next(a for a in m['options'] if a['action']==r['action'])
 parent=m['features'][m['active'].index(m['parent_position'])];alternative=m['features'][a['active_position']]
 key=hashlib.sha256(json.dumps([parent,alternative],separators=(',',':')).encode()).hexdigest()
 groups[key].append(r)
 if parent==alternative:identical.append(r)
repeated=[g for g in groups.values() if len({r['seed'] for r in g})>1]
conflicts=[g for g in repeated if len({r['delta'] for r in g})>1]
report=dict(rows=len(rows),distinct_pair_inputs=len(groups),action_indistinguishable=len(identical),cross_family_repeated_inputs=len(repeated),cross_family_conflicting_inputs=len(conflicts),repeated_rows=sum(len(g) for g in repeated),conflicting_rows=sum(len(g) for g in conflicts),conflict_groups=conflicts,repeat_kind_counts=dict(Counter(str(g[0]['kind']) for g in repeated)),exact_pair_empirical_residual_sum=sum(sum((r['delta']-sum(v['delta'] for v in g)/len(g))**2 for r in g) for g in groups.values()))
Path(__file__).with_name('collision-result.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='conflict_groups'},indent=2))
x=L.G.C.D.runtime(L.E.read(root/'protocol.json')['runtime']);ref=L.E.read(root/'roles-private.json')['fit'][0];gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,ref['seed'],20)
print('native boss',repr(gc.boss),type(gc.boss), 'obs',x.A.BASE_OBS_DIM,'deckoffset',L.G.Policy(x).reference.base.base.deck_offset)
print('boss enum keys', [k for k in type(gc.boss).__members__ if any(t in k for t in ('SLIME_BOSS','HEXAGHOST','GUARDIAN','AWAKENED'))])
