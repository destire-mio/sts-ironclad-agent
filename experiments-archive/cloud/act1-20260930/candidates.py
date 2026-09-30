"""Frozen visible predicates; no result, seed, future encounter, draw pile or RNG."""
OUTPUT=set('ANGER CLEAVE CLOTHESLINE HEAVY_BLADE HEMOKINESIS HEADBUTT IRON_WAVE POMMEL_STRIKE PERFECTED_STRIKE THUNDERCLAP TWIN_STRIKE SWORD_BOOMERANG WILD_STRIKE UPPERCUT RECKLESS_CHARGE CARNAGE BLUDGEON IMMOLATE PUMMEL SEVER_SOUL RAMPAGE DROPKICK FEED FIEND_FIRE WHIRLWIND BLOOD_FOR_BLOOD SEARING_BLOW'.split())
ATTACK_PRIORITY='CARNAGE HEMOKINESIS POMMEL_STRIKE UPPERCUT BLUDGEON HEADBUTT TWIN_STRIKE CLEAVE ANGER'.split()
KEEP=set('FEED CORRUPTION REAPER OFFERING FEEL_NO_PAIN DARK_EMBRACE SHOCKWAVE'.split())
POTIONS=['23','20','6','41','22','14','31','43','16','4','24','36']
RULES={
 'elite_low_hp':'Act1: chosen elite, HP <=40%, no potions; choose visible REST>EVENT>MONSTER>SHOP alternative (legal order ties).',
 'flame_weak':'Act1: chosen burning elite, 40%<HP<80%, no potions, <=1 nonstarter direct attack; choose non-elite REST>EVENT>MONSTER>SHOP.',
 'rest_before_forced_elite':'Act1 pre-boss campfire: chosen smith, HP<=75%, every immediate map child is elite; REST if legal, no healing-block relic.',
 'adventurer_low_hp':'Act1 Dead Adventurer: chosen continue at <=50%HP and >25% (existing fix2 covers lower); leave.',
 'wing_preserve_hp':'Act1 Golden Wing: chosen pay7HP/remove, no removable curse; take gold if legal else leave.',
 'wall_transform':'Act1 Living Wall: chosen remove, <=1 nonstarter direct attack, no removable curse; transform.',
 'early_attack':'Act1 floor<=5, <=1 nonstarter direct attack: chosen nonattack and not protected core; take one offered attack by frozen priority (no Immolate).',
 'shop_prepare_elite':'Act1 shop: policy leaves with empty potions and all immediate children elite; buy one affordable whitelisted potion (fixed priority), then leave.',
 'neow_common_relic':'Neow: chosen free remove or upgrade, free common relic is offered; choose common relic.',
}
def noutput(b):return sum(c.rstrip('+') in OUTPUT for c in b['deck'])
def match(z):
 b=z['before'];c=z.get('chosen',{});opts=z.get('options',[]);out={}
 if b['act']!=1:return out
 def pick(rule,kind=None,idx=None,item=None):
  aa=[a for a in opts if (kind is None or a['kind']==kind) and (idx is None or a['i']==idx) and (item is None or a.get('item')==item) and a['bits']!=c.get('bits')]
  if aa:out[rule]=aa[0]
 curse=b['features']['curses']>0
 if c.get('kind')=='MAP' and c.get('item')=='ELITE' and b['potion_count']==0:
  aa=[a for a in opts if a['kind']=='MAP' and a.get('item') in ('REST','EVENT','MONSTER','SHOP')]
  aa=sorted(aa,key=lambda a:['REST','EVENT','MONSTER','SHOP'].index(a['item']))
  if aa:
   if b['hp']<=.4*b['max_hp']:out['elite_low_hp']=aa[0]
   elif c.get('flame') and b['hp']<.8*b['max_hp'] and noutput(b)<=1:out['flame_weak']=aa[0]
 if c.get('kind')=='REST' and c['i']==1 and b['floor']<15 and b['hp']<=.75*b['max_hp'] and z.get('next_rooms') and set(z['next_rooms'])=={'ELITE'} and not set(b['relics'])&{'COFFEE_DRIPPER','MARK_OF_THE_BLOOM'}:
  pick('rest_before_forced_elite','REST',0)
 if c.get('kind')=='EVENT':
  ev=c['item']
  if ev=='Dead Adventurer' and c['i']==0 and .25*b['max_hp']<b['hp']<=.5*b['max_hp']:pick('adventurer_low_hp','EVENT',1)
  if ev=='Golden Wing' and c['i']==0 and not curse:
   want=1 if any(a['kind']=='EVENT' and a['i']==1 for a in opts) else 2
   pick('wing_preserve_hp','EVENT',want)
  if ev=='Living Wall' and c['i']==0 and not curse and noutput(b)<=1:pick('wall_transform','EVENT',1)
  if ev=='NEOW' and c.get('option') in ([2,1],[3,1]):
   aa=[a for a in opts if a.get('option')==[7,1]]
   if aa:out['neow_common_relic']=aa[0]
 if c.get('kind') in ('REWARD_CARD','REWARD_SKIP') and b['floor']<=5 and noutput(b)<=1 and c.get('item','').rstrip('+') not in OUTPUT|KEEP:
  aa=[a for a in opts if a['kind']=='REWARD_CARD' and a.get('item','').rstrip('+') in ATTACK_PRIORITY]
  if aa:out['early_attack']=min(aa,key=lambda a:ATTACK_PRIORITY.index(a['item'].rstrip('+')))
 if c.get('kind')=='SHOP_SKIP' and b['potion_count']==0 and not set(b['relics'])&{'SOZU'} and z.get('next_rooms') and set(z['next_rooms'])=={'ELITE'}:
  aa=[a for a in opts if a['kind']=='SHOP_POTION' and a.get('item') in POTIONS and a['price']<=b['gold']]
  if aa:out['shop_prepare_elite']=min(aa,key=lambda a:POTIONS.index(a['item']))
 return out

def augment(rec):
 # This only copies the already visible map topology from the next MAP screen.
 # No chosen route, future room contents, health or rewards are read.
 steps=rec['steps']
 for z in steps:
  if z['before']['screen'] not in ('REST_ROOM','SHOP_ROOM'):continue
  b=z['before'];n=next((q for q in steps if q['index']>z['index'] and q['before']['screen']=='MAP_SCREEN' and q['before']['floor']==b['floor']),None)
  if n:z['next_rooms']=[a['item'] for a in n['options'] if a['kind']=='MAP']
 return rec
