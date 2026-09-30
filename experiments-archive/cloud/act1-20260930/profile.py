import json,gzip,collections,statistics,hashlib
from pathlib import Path
from candidates import augment,noutput
O=Path(__file__).resolve().parent
path=O/'data/act1-decisions.jsonl.gz'
if not path.exists():path=O/'act1-decisions.jsonl.gz'
rows=[augment(json.loads(l)) for l in gzip.open(path,'rt')]
assert len(rows)==2000 and not any(r['error'] for r in rows)
byseed={r['seed']:r for r in rows}
def summarize(r,z):
 b=z['before'];before=[q for q in r['steps'] if q['index']<z['index']]
 maps=[q for q in before if q.get('chosen',{}).get('kind')=='MAP']
 sel=maps[-1] if maps else None
 battles=[q for q in before if q['kind']=='battle']
 return dict(seed=r['seed'],index=z['index'],heart_win=r['result']['win'],a1_survived=r['result']['act']>1,
  encounter=b['encounter'],room=b['room'],floor=b['floor'],hp=b['hp'],max_hp=b['max_hp'],hp_fraction=b['hp']/b['max_hp'],deck=b['deck'],deck_size=len(b['deck']),output=noutput(b),block=b['features']['block']-sum(c.rstrip('+')=='DEFEND_RED' for c in b['deck']),aoe=b['features']['aoe'],relics=b['relics'],potions=b['potions'],potion_count=b['potion_count'],potions_after=z['after']['potions'],flame=b['burning'][:2]==[b['x'],b['y']],burning_buff=b['burning'][2],neow=r['steps'][0]['chosen']['option'],prior_elites=sum(q['before']['room']=='ELITE' for q in battles),prior_event_elites=sum(q['before']['room']=='EVENT' and q['before']['encounter'] in ('LAGAVULIN_EVENT','GREMLIN_NOB','THREE_SENTRIES') for q in battles),prior_rests=sum(q['before']['screen']=='REST_ROOM' and q.get('chosen',{}).get('kind')=='REST' for q in before),prior_shops=len({q['before']['floor'] for q in before if q['before']['screen']=='SHOP_ROOM'}),last_map=sel,
  cards_added=[dict(floor=q['before']['floor'],cards=q['added'],deck_n=len(q['before']['deck'])) for q in before if q['added']],last_hp_loss=[dict(floor=q['before']['floor'],kind=q['kind'],encounter=q['before']['encounter'] if q['kind']=='battle' else q.get('chosen'),hp=q['before']['hp'],after=q['after']['hp']) for q in before if q['before']['hp']>q['after']['hp']],hp_after=z['after']['hp'],won=z['won'])
fatal=[];living=[];allb=[]
for r in rows:
 for z in r['steps']:
  if z['kind']!='battle' or z['before']['floor']>=16:continue
  s=summarize(r,z);allb.append(s)
  if not z['won']:fatal.append(s)
  elif r['result']['act']>1:living.append(s)
assert len(fatal)==201
pairs=[];used=set()
for f in sorted(fatal,key=lambda f:hashlib.sha256(('act1-match-'+str(f['seed'])).encode()).hexdigest()):
 candidates=[s for s in living if s['encounter']==f['encounter'] and (s['seed'],s['index']) not in used]
 if not candidates:candidates=[s for s in living if s['encounter']==f['encounter']]
 if not candidates:pairs.append(dict(fatal=f,control=None));continue
 def dist(s):return (abs(s['hp']-f['hp']),abs(s['hp_fraction']-f['hp_fraction']),s['room']!=f['room'],s['flame']!=f['flame'],abs(s['floor']-f['floor']),hashlib.sha256(str(s['seed']).encode()).hexdigest())
 c=min(candidates,key=dist);used.add((c['seed'],c['index']));pairs.append(dict(fatal=f,control=c,hp_diff=c['hp']-f['hp']))
(O/'fatal-profiles.json').write_text(json.dumps(fatal,ensure_ascii=False))
(O/'matched-controls.json').write_text(json.dumps(pairs,ensure_ascii=False))
(O/'all-battles.json').write_text(json.dumps(allb,ensure_ascii=False))
summary=dict(n=2000,heart_wins=sum(r['result']['win'] for r in rows),a1_nonboss=201,a1_boss=sum(r['result']['act']==1 and r['result']['floor']==16 for r in rows),encounters=[],floor=dict(sorted(collections.Counter(f['floor'] for f in fatal).items())),hp_bands=dict(collections.Counter('1-20' if f['hp']<=20 else '21-40' if f['hp']<=40 else '41-60' if f['hp']<=60 else '>60' for f in fatal)),output=dict(collections.Counter(f['output'] for f in fatal)),prior_elites=dict(collections.Counter(f['prior_elites'] for f in fatal)),prior_rests=dict(collections.Counter(f['prior_rests'] for f in fatal)),prior_shops=dict(collections.Counter(f['prior_shops'] for f in fatal)),flame=sum(f['flame'] for f in fatal),potions=dict(collections.Counter(f['potion_count'] for f in fatal)),deck_sizes=dict(collections.Counter(f['deck_size'] for f in fatal)),relics=collections.Counter(v for f in fatal for v in f['relics']).most_common(),neow=[],matched=dict(n=sum(p['control'] is not None for p in pairs),within5=sum(abs(p.get('hp_diff',999))<=5 for p in pairs),equal=sum(p.get('hp_diff',999)==0 for p in pairs)))
for key in sorted({(f['room'],f['encounter']) for f in fatal}):
 fs=[f for f in fatal if (f['room'],f['encounter'])==key];all_ls=[f for f in allb if (f['room'],f['encounter'])==key]
 summary['encounters'].append(dict(room=key[0],encounter=key[1],deaths=len(fs),entries=len(all_ls),fatal_hp_mean=statistics.mean(f['hp'] for f in fs),fatal_flame=sum(f['flame'] for f in fs),zero_output=sum(f['output']==0 for f in fs),no_potion=sum(f['potion_count']==0 for f in fs)))
for k in range(6):
 ls=[r for r in rows if r['steps'][0]['chosen']['option'][0]==k];ds=[f for f in fatal if f['neow'][0]==k]
 summary['neow'].append(dict(bonus=k,n=len(ls),deaths=len(ds),rate=len(ds)/len(ls)))
(O/'profile-summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
# Matched control budget: fixed hash of unique matched controls, max 60, outcome not used beyond A1 survival.
cs={ (p['control']['seed'],p['control']['index']):p['control'] for p in pairs if p['control']}
ctrl=sorted(cs.values(),key=lambda c:hashlib.sha256(('act1-budget-control-'+str(c['seed'])+'-'+str(c['index'])).encode()).hexdigest())[:60]
(O/'budget-control-plan.json').write_text(json.dumps([dict(seed=c['seed'],index=c['index'],floor=c['floor'],encounter=c['encounter'],sample='matched60control') for c in ctrl],indent=2))
print(json.dumps(summary,indent=2,ensure_ascii=False))
