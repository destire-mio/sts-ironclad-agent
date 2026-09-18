"""Compare one original action from an imported, identical original fixture.

Reports selection boundaries separately. It does not equate a boundary with a
complete card resolution, or a one-card fixture with whole-run parity.
"""
from pathlib import Path
import sys,os,json,copy,collections
ROOT=Path(__file__).resolve().parents[1]
REPO=Path(os.environ['STS_AGENT_ROOT']) if 'STS_AGENT_ROOT' in os.environ else next(
 p for parent in [ROOT,*ROOT.parents] for p in [parent,parent/'sts-rl-agent-pr']
 if (p/'steam/steam_mcts.py').is_file())
BUILD=Path(os.environ.get('ALIGNMENT_BUILD',str(ROOT/'build')))
os.environ['STS_LIGHTSPEED_BUILD']=str(BUILD);sys.path[:0]=[str(BUILD),str(REPO/'steam')]
import slaythespire as sts
import steam_mcts as bridge

def evidence_identity(source):
 import hashlib
 def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
 return {'source_sha256':digest(source),'module_sha256':digest(sts.__file__),'bridge_sha256':digest(bridge.__file__)}

RNG_NAMES={'ai':'aiRng','card_random':'cardRandomRng','misc':'miscRng','monster_hp':'monsterHpRng','potion':'potionRng','shuffle':'shuffleRng'}
def card(c):return (int(c.id),int(c.upgrade_count),int(c.cost_for_turn),int(c.base_cost),bool(c.free_to_play_once),int(c.special_data))
def original_card(c):
 s=bridge.card_snapshot(c);return(s['id'],s['upgrades'],s['cost'],s['base_cost'],bool(s.get('free_to_play_once',False)),s['upgrades'] if s['id']==sts.card_id_from_name('SEARING_BLOW') else s['misc'])
def original_monster(m):
 return {"id":sts.monster_id_from_name(bridge.monster_key(m)),"current_hp":m["current_hp"],"max_hp":m["max_hp"],"block":m["block"],"half_dead":m.get("half_dead",False)}
def original(g):
 c=g['combat_state'];p=c['player']
 out={'player':(p['current_hp'],p['max_hp'],p['block'],p['energy']),
      'monsters':[(m['id'],m['current_hp'],m['max_hp'],m['block'],m.get('half_dead',False)) for m in bridge.canonical_monsters(c['monsters'],original_monster)[0] if m['current_hp']>0 or m.get('half_dead')]}
 for pile in ['hand','draw_pile','discard_pile','exhaust_pile']:out[pile]=[original_card(x) for x in c[pile]]
 # Ordering is separately reported. The first scan checks card content too.
 return out
def simulator(b):
 return {'player':(b.player.cur_hp,b.player.max_hp,b.player.block,b.player.energy),
         'monsters':[(int(m.id),m.cur_hp,m.max_hp,m.block,m.half_dead) for m in b.monsters if m.alive or m.half_dead],
         **{key:[card(c) for c in getattr(b,key)] for key in ['hand','draw_pile','discard_pile','exhaust_pile']}}
def compare(row):
 result={'card':row.get('potion',row.get('card',{}).get('id')),'upgrades':row.get('upgrades',0),'bark':row.get('bark',False),'original_status':row['status']}
 if row['status']=='unplayable':
  b=sts.BattleContext.from_snapshot(bridge.build_snapshot(row['before']['game']),123)
  legal=sts.SearchAction(sts.SearchActionType.CARD,0,0).is_valid(b)
  return {**result,'status':'legality_mismatch' if legal else 'unplayable_verified'}
 if row['status']!='executed':return {**result,'status':row['status']}
 if row.get('potion')=='SmokeBomb' and row.get('after',{}).get('game',{}).get('room_phase')=='COMBAT':
  return {**result,'status':'invalid_original_boundary'}
 g=copy.deepcopy(row['before']['game']);g['combat_state']['rngs']={k:row['before']['rng'][v] for k,v in {'ai':'aiRng','card_random':'cardRandomRng','misc':'miscRng','monster_hp':'monsterHpRng','potion':'potionRng','shuffle':'shuffleRng'}.items()}
 snap=bridge.build_snapshot(g);b=sts.BattleContext.from_snapshot(snap,123)
 action=sts.SearchAction(sts.SearchActionType.POTION if 'potion' in row else sts.SearchActionType.CARD,0,0)
 if not action.is_valid(b):return {**result,'status':'legality_mismatch'}
 action.execute(b)
 if 'combat_state' not in row['after']['game']:return {**result,'status':'terminal_boundary','simulator_outcome':str(b.outcome),'original_phase':row['after']['game']['room_phase']}
 if b.input_state==sts.InputState.CARD_SELECT or row['after']['game']['screen_type'] not in ['NONE']:
  return {**result,'status':'selection_boundary','simulator_state':str(b.input_state),'original_screen':row['after']['game']['screen_type']}
 before_diff={};expected=original(g);actual=simulator(sts.BattleContext.from_snapshot(snap,123))
 for k in expected:
  if expected[k]!=actual[k]:before_diff[k]={'original':expected[k],'simulator':actual[k]}
 if before_diff:return {**result,'status':'import_mismatch','differences':before_diff}
 expected=original(row['after']['game']);actual=simulator(b);diff={}
 expected['potions']=[sts.potion_id_from_name(bridge.POTION_ALIASES.get(p['id'],p['id'])) for p in row['after']['game']['potions']]
 actual['potions']=[int(p) for p in b.potions]
 expected['rng']={key:bridge.rng_snapshot(row['after']['rng'][name]) for key,name in RNG_NAMES.items()}
 actual['rng']=b.rng_states
 for key in expected:
  if expected[key]!=actual[key]:diff[key]={'original':expected[key],'simulator':actual[key]}
 power_diff=[]
 deferred_powers=[]
 for owner,objects in [('player',[b.player]),('monster',b.monsters)]:
  sources=[row['after']['game']['combat_state']['player']] if owner=='player' else row['after']['game']['combat_state']['monsters']
  for obj,source in zip(objects,sources):
   for p in source['powers']:
    if p['id'] in ['Panache','Berserk'] or p['id'].startswith('TheBomb'):
     deferred_powers.append(p['id']);continue
    if p['id'] in bridge.IGNORED_MONSTER_POWERS and owner=='monster':continue
    s=bridge.power_snapshot(p,owner);typ=sts.PlayerStatus if owner=='player' else sts.MonsterStatus
    if p['amount']==-1:
     value=int(obj.has_status(typ(s['id'])))
    else:value=obj.get_status(typ(s['id']))
    if value!=s['amount']:power_diff.append({'owner':owner,'power':p['id'],'original':s['amount'],'simulator':value})
 if power_diff:diff['powers']=power_diff
 return {**result,'status':'mismatch' if diff else ('deferred_power_behavior' if deferred_powers else 'passed'),'differences':diff,'deferred_powers':deferred_powers}
def main():
 source=Path(sys.argv[1]);rows=json.loads(source.read_text());results=[]
 for r in rows:
  try:out=compare(r)
  except Exception as e:out={'card':r.get('potion',r.get('card',{}).get('id')),'upgrades':r.get('upgrades',0),'bark':r.get('bark',False),'status':'unsupported','error':str(e)}
  results.append(out)
 dest=ROOT/'evidence'/('card-comparison-'+source.parent.name+'.json');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps({**evidence_identity(source),'scope':'one action from controlled original Ironclad A20 fixture','source':str(source),'module':sts.__file__,'counts':dict(collections.Counter(r['status'] for r in results)),'results':results},indent=2)+'\n')
 print(dest);print(collections.Counter(r['status'] for r in results))
 for r in results:
  if r['status'] in ['mismatch','legality_mismatch','unsupported','import_mismatch']:print(json.dumps(r))
if __name__=='__main__':main()
