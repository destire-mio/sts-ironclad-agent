"""Replay a natural original run in GameContext + BattleContext without resync.

Adapter-only UI screens are skipped; choices are matched to the current original
screen. Stop at the first discrepancy; never import the original's later state.
"""
from compare_cards import *
from winner_ui import event_action_order

def deck_original(g):
 return [(bridge.card_snapshot(c)['id'],int(c['upgrades']),int(c['upgrades']) if c['id']=='Searing Blow' else bridge.card_snapshot(c)['misc']) for c in g['deck']]
def deck_sim(s):return [(int(c.id),int(c.upgrade_count),int(c.misc)) for c in s.deck]

def outside_differences(view,gc):
 g=view['game'];pairs=[('hp',g['current_hp'],gc.cur_hp),('max_hp',g['max_hp'],gc.max_hp),('gold',g['gold'],gc.gold),('deck',deck_original(g),deck_sim(gc)),('floor',g['floor'],gc.floor_num),('act',g['act'],gc.act)]
 pairs.append(('keys',[view.get('ruby',False),view.get('emerald',False),view.get('sapphire',False)],[gc.red_key,gc.green_key,gc.blue_key]))
 pairs.append(('potions',[sts.potion_id_from_name(bridge.POTION_ALIASES.get(p['id'],p['id'])) for p in g['potions']],gc.potions))
 pairs.append(('relics',[sts.relic_id_from_name(r['id']) for r in g['relics']],[int(r.id) for r in gc.relics]))
 persistent={'Happy Flower','Incense Burner','InkBottle','Nunchaku','Pen Nib','Sundial','Omamori','Girya','NeowsBlessing'}
 stored={int(r.id):r.data for r in gc.relics}
 for relic in g['relics']:
  if relic['id'] in persistent and relic.get('counter',-1)>=0:
   pairs.append(('relic_counter:'+relic['id'],relic['counter'],stored.get(sts.relic_id_from_name(relic['id']))))
 if g['screen_type']=='MAP':
  symbols={'$':0,'R':1,'?':2,'E':3,'M':4,'T':5,'B':6}
  expected=[];actual=[]
  for node in g['map']:
   x,y=node['x'],node['y']
   if y>14:continue
   expected.append((x,y,symbols[node['symbol']],sorted(c['x'] for c in node['children']) if y<14 else []))
   actual.append((x,y,int(gc.map_node_room(x,y)),sorted(gc.map_node_children(x,y)) if y<14 else []))
  pairs.append(('map_nodes_and_edges',expected,actual))
 if g['screen_type']=='COMBAT_REWARD' and gc.screen_state==sts.ScreenState.REWARDS:
  rewards=g['screen_state']['rewards'];sim=gc.rewards
  expected={'gold':[r['gold'] for r in rewards if r['reward_type'] in ['GOLD','STOLEN_GOLD']],
            'relics':[sts.relic_id_from_name(r['relic']['id']) for r in rewards if r['reward_type']=='RELIC'],
            'potions':[sts.potion_id_from_name(r['potion']['id']) for r in rewards if r['reward_type']=='POTION'],
            'card_count':sum(r['reward_type']=='CARD' for r in rewards),
            'emerald':any(r['reward_type']=='EMERALD_KEY' for r in rewards),
            'sapphire':any(r['reward_type']=='SAPPHIRE_KEY' for r in rewards)}
  actual={k:sim[k] for k in ['gold','relics','potions','emerald','sapphire']};actual['card_count']=len(sim['cards'])
  pairs.append(('rewards',expected,actual))
 if g['screen_type']=='EVENT' and g['floor']>0 and gc.screen_state==sts.ScreenState.EVENT_SCREEN:
  pairs.append(('event',g['screen_state']['event_id'],gc.event_id))
 # Combat-local generators reset at each room; these seven persist between rooms.
 for name in ['eventRng','treasureRng','relicRng','potionRng','cardRng','merchantRng','monsterRng']:
  pairs.append((name,bridge.rng_snapshot(view['rng'][name]),gc.rng_states[name]))
 return {key:{'original':wanted,'simulator':got} for key,wanted,got in pairs if wanted!=got}

def run(source):
 rows=[json.loads(line) for line in source.read_text().splitlines()];gc=None;b=None;previous=None;pending=0;selected_reward=0;steps=[];pending_game=None;event_steps={}
 result={**evidence_identity(source),'source':str(source),'resynchronized':False,'strict':os.environ.get('ALIGNMENT_STRICT')=='1','external_inputs':[], 'steps':steps}
 for record_index,row in enumerate(rows):
  req=row['request'];response=row['response'];command=req.get('command')
  if req.get('op')=='controlled_run_fixture':command='controlled_run_fixture'
  if not command or not response['ok']:continue
  after=response['result'];g=after['game'];words=command.lower().split();typ=words[0];step={'record_index':record_index,'command':command,'floor':g['floor'],'screen':g['screen_type']};diff={}
  try:
   if typ=='start':gc=sts.GameContext(sts.CharacterClass.IRONCLAD,int(g['seed']),20)
   elif typ=='controlled_run_fixture':
    result['controlled_fixture']=True;gc.cur_hp=gc.max_hp=2000
    while gc.deck:gc.remove_card(0)
    for _ in range(5):
     card=sts.Card(sts.CardId(sts.card_id_from_name('SEARING_BLOW')))
     for _ in range(30):card.upgrade()
     gc.obtain_card(card)
    for relic in ['Coffee Dripper','Fusion Hammer','Cursed Key','Sozu']:gc.obtain_relic(sts.RelicId(sts.relic_id_from_name(relic)))
   else:
    if 'rule_input_play_time' in after:
     gc.set_play_time(after['rule_input_play_time'])
     if 'play_time_seconds' not in result['external_inputs']:result['external_inputs'].append('play_time_seconds')
    old=previous['game'];screen=old['screen_type'];idx=int(words[1]) if len(words)>1 and words[1].isdigit() else 0;action=None
    if b is not None and b.outcome!=sts.Outcome.UNDECIDED:
     # The simulator joins these transitions to battle exit; the original
     # displays a victory screen / Heart dialogue before entering the next room.
     if g['room_phase']=='COMBAT' or g['act']>gc.act or g['screen_type']=='GAME_OVER':
      b.exit_battle(gc);b=None
    elif b is not None:
     def target_index(native_index):
      _,indices=bridge.canonical_monsters(old['combat_state']['monsters'],original_monster)
      return indices.index(native_index)
     if typ=='play':action=sts.SearchAction(sts.SearchActionType.CARD,idx-1,target_index(int(words[2])) if len(words)>2 else 0)
     elif typ=='end':action=sts.SearchAction(sts.SearchActionType.END_TURN)
     elif typ=='potion':action=sts.SearchAction(sts.SearchActionType.POTION,int(words[2]),target_index(int(words[3])) if len(words)>3 else 0)
     elif typ=='choose':
      legal=sts.get_legal_actions(b)
      if legal and all(a.action_type==sts.SearchActionType.MULTI_CARD_SELECT for a in legal):pending|=1<<idx
      else:action=legal[idx]
     elif typ=='confirm' and b.input_state==sts.InputState.CARD_SELECT:action=sts.SearchAction(sts.SearchActionType.MULTI_CARD_SELECT,pending);pending=0
     if action is not None:
      if not action.is_valid(b):raise ValueError('combat adapter selected illegal action '+command)
      action.execute(b)
     if b.outcome!=sts.Outcome.UNDECIDED:
      if g['screen_type']!='COMPLETE' or g['act']<3:b.exit_battle(gc);b=None
    elif typ=='choose':
     event_key=(old['floor'],old['screen_state'].get('event_id'));event_step=event_steps.get(event_key,0)
     if screen=='EVENT':event_steps[event_key]=event_step+1
     if screen=='EVENT' and event_step==0 and (event_key[1] in ['Falling','SensoryStone'] or (event_key[1]=='Liars Game' and idx==0)):
      pass # Original introduction/acceptance dialogue precedes the rule action.
     elif screen=='EVENT' and old['screen_state'].get('event_id')=='Wheel of Change' and ('spin' in old.get('choice_list',[]) or 'spin' in g.get('choice_list',[])):
      pass # Enter-wheel and spin UI; claim applies the generated result.
     elif screen=='EVENT' and gc.screen_state in [sts.ScreenState.CARD_SELECT,sts.ScreenState.BATTLE]:
      pass # Original dialogue is catching up to the simulator's child screen.
     elif screen=='EVENT' and gc.screen_state==sts.ScreenState.MAP_SCREEN:
      pass # Original event text has a final Leave button; simulator already left.
     elif screen=='EVENT' and old.get('neow',{}).get('stage') in ['talk','leave']:
      if old['neow']['stage']=='leave' and gc.screen_state==sts.ScreenState.REWARDS:action=sts.GameAction(6<<27)
     elif screen=='MAP':
      nodes=old['screen_state'].get('next_nodes',[]);action=sts.GameAction(nodes[idx]['x'] if nodes else (3 if gc.act==4 else 0))
     elif screen=='CARD_REWARD':
      offered=gc.rewards['cards'][selected_reward];cards=old['screen_state']['cards']
      if [(int(c.id),bool(c.upgraded)) for c in offered]!=[(bridge.card_snapshot(c)['id'],bool(c['upgrades'])) for c in cards]:raise ValueError('card offers differ')
      action=sts.GameAction(((5 if old.get('choice_list',[])[idx]=='bowl' else idx)<<8)|selected_reward)
     elif screen=='COMBAT_REWARD':
      reward=old['screen_state']['rewards'][idx];kind=reward['reward_type'];rank=sum(x['reward_type']==kind for x in old['screen_state']['rewards'][:idx])
      if kind in ['GOLD','STOLEN_GOLD']:rank=sum(x['reward_type'] in ['GOLD','STOLEN_GOLD'] for x in old['screen_state']['rewards'][:idx])
      if kind=='CARD':selected_reward=rank
      else:action=sts.GameAction(({'GOLD':1,'STOLEN_GOLD':1,'EMERALD_KEY':2,'SAPPHIRE_KEY':2,'POTION':3,'RELIC':4}[kind]<<27)|rank)
     elif screen=='REST':
      choices=old['screen_state']['rest_options'];action=sts.GameAction({'rest':0,'smith':1,'recall':2,'lift':3,'toke':4,'dig':5}[choices[idx]])
     elif screen=='CHEST':
      if old['screen_state'].get('chest_type')!='BossChest':action=sts.GameAction(0)
     elif screen=='GRID' and gc.screen_state==sts.ScreenState.CARD_SELECT:
      chosen=old['screen_state']['cards'][idx]
      deck_idx=next((i for i,c in enumerate(old['deck']) if c['uuid']==chosen['uuid']),None)
      action=sts.GameAction(list(gc.selection_deck_indices).index(deck_idx)) if deck_idx is not None else sts.GameAction(idx)
     elif screen in ['EVENT','GRID','BOSS_REWARD']:
      options=[a for a in sts.get_legal_game_actions(gc) if not a.is_potion_action]
      order=event_action_order(old,[a.bits for a in options])
      action=next(a for a in options if a.bits==order[idx])
     else:raise ValueError('unmapped original choice '+screen)
    elif typ in ['proceed','skip']:
     if typ=='skip' and screen=='CARD_REWARD':pass # Closing the card screen leaves this offer unclaimed.
     elif typ=='skip' and screen=='BOSS_REWARD':pending_game=sts.GameAction(3)
     elif typ=='proceed' and screen=='CHEST' and old['screen_state'].get('chest_type')=='BossChest':action=pending_game;pending_game=None
     elif screen=='REST' and gc.screen_state==sts.ScreenState.REST_ROOM and not old['screen_state']['rest_options']:action=sts.GameAction(6)
     elif gc.screen_state in [sts.ScreenState.REWARDS,sts.ScreenState.SHOP_ROOM]:action=sts.GameAction(6<<27)
    elif typ=='confirm':action=pending_game;pending_game=None
    elif typ=='cancel':pending_game=None
    else:raise ValueError('unmapped original command '+command)
    if action is not None and isinstance(action,sts.GameAction):
     if not action.is_valid(gc):raise ValueError('game adapter selected illegal action '+command+' '+str(gc.screen_state)+' from '+screen+' at '+str(g['floor']))
     if screen=='GRID' and typ=='choose' and g['screen_type']=='GRID' and g['screen_state'].get('confirm_up'):
      pending_game=action
     else:action.execute(gc)
   if gc.screen_state==sts.ScreenState.BATTLE and b is None and g['room_phase']=='COMBAT':
    b=sts.BattleContext();b.init(gc)
   if b is not None and g['room_phase']=='COMBAT' and g['screen_type']=='NONE' and b.input_state==sts.InputState.PLAYER_NORMAL:
    expected=original(g);actual=simulator(b);expected['rng']={k:bridge.rng_snapshot(after['rng'][v]) for k,v in RNG_NAMES.items()};actual['rng']=b.rng_states
    diff={k:{'original':expected[k],'simulator':actual[k]} for k in expected if expected[k]!=actual[k]}
    if os.environ.get('ALIGNMENT_STRICT')=='1':
     from compare_powers import extras
     diff.update(extras(g,b))
   elif b is None:
    diff=outside_differences(after,gc)
   elif b.outcome==sts.Outcome.PLAYER_VICTORY and g['room_phase']!='COMBAT':
    step['adapter_boundary']='waiting for original victory/act transition'
   elif g['room_phase']!='COMBAT':
    diff={'combat_outcome':{'original':g['room_phase'],'simulator':str(b.outcome)}}
   step['simulator_screen']=str(gc.screen_state)
   step['differences']=diff;steps.append(step);previous=after
   if diff:return {**result,'status':'mismatch','first_mismatch':step}
  except Exception as error:
   return {**result,'status':'adapter_or_engine_error','error':str(error),'failed_step':step}
 return {**result,'status':'record_replayed','floor':previous['game']['floor'],'original_terminal':previous['game'].get('screen_state') if previous['game']['screen_type']=='GAME_OVER' else None,'simulator_outcome':str(gc.outcome)}
if __name__=='__main__':
 source=Path(sys.argv[1])
 try:result=run(source)
 except Exception as e:result={'source':str(source),'status':'adapter_or_engine_error','error':str(e)}
 destination=ROOT/'evidence'/('run-replay-'+source.parent.name+'.json');destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='steps'},indent=2))
