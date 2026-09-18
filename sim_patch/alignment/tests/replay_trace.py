"""Continuous natural-run comparison from original recorded responses.

Only seed and recorded player commands drive GameContext/BattleContext.
Later original HP, cards, RNG and powers are observations, never imported.
"""
from compare_cards import *
from replay_run import outside_differences
from compare_powers import extras

def write_progress(path,value):
 if os.environ.get('ALIGNMENT_QUIET_PROGRESS')!='1':path.write_text(json.dumps(value)+'\n')

class TraceReplay:
 def __init__(self,p,trace,d):
  self.p=p;self.trace=trace;self.d=d;self.rows=[];self.view={};self.event_steps={};self.shop_slots={}
  self.gc=sts.GameContext(sts.CharacterClass.IRONCLAD,trace['seed'],20)
 def call(self,command):
  self.view=self.p.call('command',command=command)
  self.rows.append({'command':command,'floor':self.view['game']['floor'],'screen':self.view['game']['screen_type']})
  return self.view
 def check(self,b=None):
  g=self.view['game']
  if b is None:diff=outside_differences(self.view,self.gc)
  elif g['screen_type']=='NONE' and g['room_phase']=='COMBAT' and b.input_state==sts.InputState.PLAYER_NORMAL:
   wanted=original(g);got=simulator(b)
   wanted['rng']={k:bridge.rng_snapshot(self.view['rng'][v]) for k,v in RNG_NAMES.items()};got['rng']=b.rng_states
   diff={k:{'original':wanted[k],'simulator':got[k]} for k in wanted if wanted[k]!=got[k]};diff.update(extras(g,b))
  else:return
  self.rows[-1]['differences']=diff
  if diff:raise ValueError('rules mismatch '+str(list(diff)))
 def align(self):
  target={sts.ScreenState.EVENT_SCREEN:['EVENT'],sts.ScreenState.REWARDS:['COMBAT_REWARD'],sts.ScreenState.BOSS_RELIC_REWARDS:['BOSS_REWARD'],sts.ScreenState.CARD_SELECT:['GRID'],sts.ScreenState.MAP_SCREEN:['MAP'],sts.ScreenState.TREASURE_ROOM:['CHEST'],sts.ScreenState.REST_ROOM:['REST'],sts.ScreenState.SHOP_ROOM:['SHOP_SCREEN'],sts.ScreenState.BATTLE:['NONE']}[self.gc.screen_state]
  for _ in range(20):
   g=self.view['game'];screen=g['screen_type'];available=self.view['available_commands']
   if self.gc.screen_state==sts.ScreenState.BATTLE and g['room_phase']=='COMBAT' and g['floor']==self.gc.floor_num:return
   neow=g.get('neow',{}).get('stage')
   if screen in target and not(screen=='EVENT' and neow in ['talk','leave']):return
   if 'confirm' in available:self.call('confirm')
   elif screen=='EVENT' and 'choose' in available:self.call('choose 0')
   elif screen=='SHOP_ROOM' and self.gc.screen_state==sts.ScreenState.SHOP_ROOM and 'choose' in available:self.call('choose 0')
   elif screen=='CHEST' and g['screen_state'].get('chest_type')=='BossChest' and 'choose' in available:self.call('choose 0')
   elif 'proceed' in available:self.call('proceed')
   elif 'skip' in available:self.call('skip')
   else:raise ValueError('cannot settle original '+screen+' to '+str(self.gc.screen_state)+' '+str(available))
  raise ValueError('original UI failed to settle')
 def outside(self,a):
  self.align();self.check();g=self.view['game'];screen=g['screen_type'];idx=a.idx1;kind=int(a.rewards_action_type)
  if not a.is_valid(self.gc):raise ValueError('trace game action invalid '+str(a))
  if a.is_potion_action:
   self.call('potion '+('discard' if a.bits&0x40000000 else 'use')+' '+str(idx))
  elif screen=='MAP':
   nodes=g['screen_state'].get('next_nodes',[]);choice=next((i for i,n in enumerate(nodes) if n['x']==idx),0 if not nodes else None)
   if choice is None:raise ValueError('map path unavailable')
   self.call('choose '+str(choice))
  elif screen=='REST':
   if idx==6:self.call('proceed')
   else:self.call('choose '+str(g['screen_state']['rest_options'].index(['rest','smith','recall','lift','toke','dig'][idx])))
  elif screen=='CHEST':self.call('choose 0' if idx==0 else 'proceed')
  elif screen=='COMBAT_REWARD':
   if kind==6:self.call('proceed')
   else:
    types={0:['CARD'],1:['GOLD','STOLEN_GOLD'],2:['EMERALD_KEY','SAPPHIRE_KEY'],3:['POTION'],4:['RELIC']}[kind]
    choices=[i for i,r in enumerate(g['screen_state']['rewards']) if r['reward_type'] in types]
    self.call('choose '+str(choices[idx]))
    if kind==0:
     cards=self.view['game']['screen_state']['cards'];offered=self.gc.rewards['cards'][idx]
     if [(int(c.id),int(c.upgrade_count)) for c in offered]!=[(bridge.card_snapshot(c)['id'],c['upgrades']) for c in cards]:raise ValueError('card offers mismatch')
     self.call('choose '+str(self.view['game']['choice_list'].index('bowl') if a.idx2==5 else a.idx2))
  elif screen=='BOSS_REWARD':self.call('skip' if idx==3 else 'choose '+str(idx))
  elif screen=='GRID':
   if kind==6:self.call('cancel')
   else:
    deck_idx=self.gc.selection_deck_indices[idx];cards=g['screen_state']['cards']
    if deck_idx>=0:
     uuid=g['deck'][deck_idx]['uuid'];choice=next(i for i,c in enumerate(cards) if c['uuid']==uuid)
    else:choice=idx
    self.call('choose '+str(choice))
    if 'confirm' in self.view['available_commands']:self.call('confirm')
  elif screen=='SHOP_SCREEN':
   stock=g['screen_state'];choices=g.get('choice_list',[])
   if kind==6:self.call('leave')
   elif kind==5:self.call('choose '+str(choices.index('purge')))
   elif kind==0:
    card,price=self.gc.get_shop_cards()[idx];matches=[c for c in stock['cards'] if bridge.card_snapshot(c)['id']==int(card.id) and c['price']==price]
    if len(matches)!=1:raise ValueError('ambiguous shop card')
    self.call('choose '+str(choices.index(matches[0]['name'].lower())))
   elif kind in [3,4]:
    bucket='relics' if kind==4 else 'potions';key=(g['floor'],bucket)
    slots=self.shop_slots.setdefault(key,[x['id'] for x in stock[bucket]])
    chosen=next(x for x in stock[bucket] if x['id']==slots[idx])
    rank=next(i for i,x in enumerate(stock[bucket]) if x is chosen)
    self.call('choose '+str(choices.index(chosen['name'].lower())))
    if any(r['id']=='The Courier' for r in self.view['game']['relics']):slots[idx]=self.view['game']['screen_state'][bucket][rank]['id']
    else:slots[idx]=None
   else:raise ValueError('unsupported shop trace kind '+str(kind))
  elif screen=='EVENT':
   key=(g['floor'],g['screen_state'].get('event_id'));step=self.event_steps.get(key,0)
   if step==0 and (key[1] in ['Falling','SensoryStone'] or (key[1]=='Liars Game' and idx==0)):
    self.call('choose 0');g=self.view['game']
   if key[1]=='Wheel of Change':
    while 'spin' in self.view['game'].get('choice_list',[]):self.call('choose 0')
   options=[x for x in sts.get_legal_game_actions(self.gc) if not x.is_potion_action]
   choice=next(i for i,x in enumerate(options) if x.bits==a.bits)
   self.call('choose '+str(choice));self.event_steps[key]=step+1
  else:raise ValueError('unmapped original '+screen)
  a.execute(self.gc)
 def combat(self,row):
  self.align();b=sts.BattleContext();b.init(self.gc);self.check(b)
  for raw in row['actions']:
   bits=raw&0xffffffff;a=sts.SearchAction(sts.SearchActionType(bits>>29),bits&0xffff,(bits>>16)&0x1fff)
   if not a.is_valid(b):raise ValueError('trace combat action invalid '+str(a))
   if int(a.action_type) in [0,1,4]:
    snap=bridge.build_snapshot(self.view['game']);self.call(bridge.action_command(a,b,snap).lower())
   elif a.action_type==sts.SearchActionType.SINGLE_CARD_SELECT:
    legal=sts.get_legal_actions(b);idx=next(i for i,x in enumerate(legal) if x.bits==a.bits)
    self.call('choose '+str(idx))
   else:
    screen=self.view['game']['screen_state'];options=screen.get('cards',screen.get('hand',[]))
    # A mask action resolves selected hand cards from right to left in the simulator.
    # Preserve that explicit action order in the original UI.
    chosen=[options[i]['uuid'] for i in reversed(a.selected_idxs)]
    for uuid in chosen:
     screen=self.view['game']['screen_state'];options=screen.get('cards',screen.get('hand',[]))
     self.call('choose '+str(next(i for i,c in enumerate(options) if c['uuid']==uuid)))
    if 'confirm' in self.view['available_commands']:self.call('confirm')
   a.execute(b)
   if b.input_state==sts.InputState.PLAYER_NORMAL and 'confirm' in self.view['available_commands']:self.call('confirm')
   self.check(b)
  if int(b.outcome)!=row['battle_outcome']:raise ValueError('trace combat outcome changed')
  b.exit_battle(self.gc)
 def run(self):
  self.p.call('observe');self.call('start ironclad 20 '+sts.get_seed_str(self.trace['seed']))
  for n,row in enumerate(self.trace['steps']):
   if (self.gc.floor_num,self.gc.cur_hp,int(self.gc.screen_state))!=(row['floor'],row['hp'],row['screen']):raise ValueError('recorded trace state mismatch at row '+str(n))
   if row['screen']==9:self.combat(row)
   else:
    for raw in row['actions']:self.outside(sts.GameAction(raw&0xffffffff))
   write_progress(self.d/'progress.json',{'row':n,'floor':self.gc.floor_num,'hp':self.gc.cur_hp,'commands':len(self.rows)})
  for _ in range(10):
   if self.view['game']['screen_type']=='GAME_OVER':break
   if 'proceed' in self.view['available_commands']:self.call('proceed')
   else:raise ValueError('missing original terminal')
  self.check()
  return {'status':'natural_trace_replayed','floor':self.gc.floor_num,'hp':self.gc.cur_hp,'terminal':self.view['game']['screen_state'],'simulator_outcome':str(self.gc.outcome)}


class RecordedProbe:
 def __init__(self,rows):self.rows=rows;self.position=0
 def call(self,op,**args):
  if op not in ['observe','command']:raise ValueError('recorded natural replay forbids fixture/state import')
  row=self.rows[self.position];self.position+=1;request=row['request']
  if request['op']!=op or (op=='command' and request['command'].lower()!=args['command'].lower()):
   raise ValueError('recorded command differs at '+str(self.position)+': '+str(request)+' vs '+str(args))
  if not row['response']['ok']:raise ValueError('original command failed')
  return row['response']['result']

if __name__=='__main__':
 import gzip
 source=Path(sys.argv[1]);fixture=json.load(gzip.open(source,'rt') if source.suffix=='.gz' else source.open())
 if fixture['trace']['controlled_fixture']:raise ValueError('natural trace required')
 os.environ['ALIGNMENT_QUIET_PROGRESS']='1';p=RecordedProbe(fixture['rpc']);runner=TraceReplay(p,fixture['trace'],source.parent)
 try:
  result=runner.run()
  if p.position!=len(p.rows):raise ValueError('unconsumed original commands')
 except Exception as e:result={'status':'mismatch_or_adapter_error','error':str(e),'record':p.position}
 result.update(evidence_identity(source));result.update(resynchronized=False,controlled_fixture=False,commands=len(runner.rows),steps=runner.rows)
 destination=Path(os.environ.get('ALIGNMENT_REPORT_DIR',str(ROOT/'evidence')))/'natural-trace-comparison.json';destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k!='steps'}));sys.exit(0 if result['status']=='natural_trace_replayed' else 1)
