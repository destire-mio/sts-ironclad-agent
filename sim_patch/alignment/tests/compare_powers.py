"""Visible power and intent comparison, independent of state restoration."""
from compare_cards import *
PLAYER_BOOL={'BARRICADE','CORRUPTION','CONFUSED','PEN_NIB','SURROUNDED','HEX','DRAW_REDUCTION'}
MONSTER_INTERNAL={'ASLEEP','MINION_LEADER'}
MONSTER_BOOL={'BARRICADE','MINION','PAINFUL_STABS','REGROW','SHIFTING','STASIS'}

def player_expected(g):
 c=g['combat_state'];out={};bombs=[0,0,0]
 for p in c['player']['powers']:
  if p['id']=='Berserk':continue
  snap=bridge.power_snapshot(p,'player');key=sts.PlayerStatus(snap['id']).name
  if key=='THE_BOMB':bombs[snap['bomb_turns']-1]+=snap['amount'];continue
  if snap['amount'] or key=='PANACHE':out[key]=1 if key in PLAYER_BOOL else snap['amount']
  if key=='PANACHE':out['panache_counter']=snap['counter']
  if key=='COMBUST':out['combust_hp_loss']=snap.get('misc',1)
 out['bombs']=bombs
 out['gold']=g['gold']
 out['energy_per_turn']=c.get('energy_per_turn',3)+sum(p['amount'] for p in c['player']['powers'] if p['id']=='Berserk')
 out['card_draw_per_turn']=c.get('card_draw_per_turn',5-int(any(p['id']=='Draw Reduction' for p in c['player']['powers'])))
 return out

def player_actual(b):
 p=b.player;out={}
 for name,value in sts.PlayerStatus.__members__.items():
  if name in {'INVALID','THE_BOMB'} or not p.has_status(value):continue
  amount=1 if name in PLAYER_BOOL else p.get_status(value)
  if amount or name=='PANACHE':out[name]=amount
  if name=='PANACHE':out['panache_counter']=p.panache_counter
  if name=='COMBUST':out['combust_hp_loss']=p.combust_hp_loss
 out.update(gold=p.gold,bombs=list(p.bombs),energy_per_turn=p.energy_per_turn,card_draw_per_turn=p.card_draw_per_turn)
 return out

def monster_expected(raw):
 out=original_monster(raw);powers={}
 for p in raw['powers']:
  if p['id'] in bridge.IGNORED_MONSTER_POWERS:continue
  s=bridge.power_snapshot(p,'monster');key=sts.MonsterStatus(s['id']).name
  if s['amount'] or key in {'REACTIVE','TIME_WARP','SLOW','INVINCIBLE'}:powers[key]=s['amount']
 out['powers']=powers;out['move']=bridge.move_id(raw)
 out['attack']=(raw.get('move_base_damage'),max(1,raw.get('move_hits',1))) if str(raw.get('intent','')).startswith('ATTACK') and raw.get('move_base_damage',-1)>=0 else None
 return out

def extras(g,b):
 expected=player_expected(g);actual=player_actual(b);diff={}
 if expected!=actual:diff['player_powers']={'original':expected,'simulator':actual}
 raw=bridge.canonical_monsters(g['combat_state']['monsters'],monster_expected)[0]
 expected=[];actual=[]
 for m in raw:
  if m['current_hp']<=0 and not m.get('half_dead'):continue
  expected.append((m['id'],m['move'],m['powers']))
 for m in b.monsters:
  if not m.alive and not m.half_dead:continue
  powers={}
  for name,value in sts.MonsterStatus.__members__.items():
   if name in MONSTER_INTERNAL|{'INVALID'} or not m.has_status(value):continue
   amount=m.get_status(value)
   if amount or name in {'REACTIVE','TIME_WARP','SLOW','INVINCIBLE'}:powers[name]=amount
  if m.strength:powers['STRENGTH']=m.strength
  actual.append((m.id,m.move_id,powers))
 if expected!=actual:diff['monster_powers_and_intents']={'original':expected,'simulator':actual}
 visible=[m for m in raw if m['current_hp']>0 or m.get('half_dead')]
 simulated=[m for m in b.monsters if m.alive or m.half_dead]
 if len(visible)==len(simulated):
  attacks=[]
  for wanted,got in zip(visible,simulated):
   if wanted['attack'] is not None and tuple(wanted['attack'])!=tuple(got.intent_damage(b)):
    attacks.append({'monster':wanted['id'],'original':wanted['attack'],'simulator':got.intent_damage(b)})
  if attacks:diff['monster_attack_damage_and_count']=attacks
 for key,wanted in g['combat_state'].get('relic_combat_state',{}).items():
  got=b.snapshot_counters[key]
  if got!=wanted:diff[key]={'original':wanted,'simulator':got}
 return diff
