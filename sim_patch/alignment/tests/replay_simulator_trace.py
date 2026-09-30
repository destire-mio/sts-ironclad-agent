"""Replay recorded player choices under repaired rules; never copy later state."""
from compare_cards import *
from trace_selection import recorded_game_action
source=Path(sys.argv[1]);trace=json.loads(source.read_text());g=sts.GameContext(sts.CharacterClass.IRONCLAD,trace['seed'],20)
if trace['controlled_fixture']:raise ValueError('natural trace required')
steps=[];result={**trace,'source_trace':str(source),'steps':steps,'status':'truncated','removed_legacy_card_skips':[],'action_translations':[]}
try:
 for old in trace['steps']:
  if g.outcome!=sts.GameOutcome.UNDECIDED:break
  row={**old,'hp':g.cur_hp,'actions':[]}
  if g.screen_state==sts.ScreenState.CARD_SELECT:row['selection_deck_indices']=list(g.selection_deck_indices)
  if (g.floor_num,int(g.screen_state))!=(old['floor'],old['screen']):raise ValueError('trace screen or floor changed')
  if old['screen']==9:
   b=sts.BattleContext();b.init(g)
   for raw in old['actions']:
    if b.outcome!=sts.Outcome.UNDECIDED:break
    bits=raw&0xffffffff;a=sts.SearchAction(sts.SearchActionType(bits>>29),bits&0xffff,(bits>>16)&0x1fff)
    if not a.is_valid(b):raise ValueError('recorded combat action no longer legal '+str(a))
    a.execute(b);row['actions'].append(raw)
   row.update(battle_outcome=int(b.outcome),ending_hp=b.player.cur_hp)
   if b.outcome==sts.Outcome.UNDECIDED:raise ValueError('recorded battle did not finish')
   b.exit_battle(g)
  else:
   for raw in old['actions']:
    a,note=recorded_game_action(sts,g,raw,old)
    if note is not None:result['action_translations'].append(note)
    if '--migrate-legacy-card-skips' in sys.argv and g.screen_state==sts.ScreenState.REWARDS and int(a.rewards_action_type)==0 and a.idx2==5 and a.idx1<len(g.rewards['cards']) and not any(int(r.id)==sts.relic_id_from_name('Singing Bowl') for r in g.relics):
     result['removed_legacy_card_skips'].append({'floor':g.floor_num,'bits':raw});continue
    if not a.is_valid(g):raise ValueError('recorded outside choice no longer legal')
    a.execute(g);row['actions'].append(a.bits)
  if 'bits' in row and len(row['actions'])==1:row['bits']=row['actions'][0]
  steps.append(row)
 result['status']='heart_victory' if g.outcome==sts.GameOutcome.PLAYER_VICTORY else 'simulator_death' if g.outcome==sts.GameOutcome.PLAYER_LOSS else 'truncated'
except Exception as e:result.update(status='invalid_recorded_action',error=str(e))
result.update(floor=g.floor_num,act=g.act,hp=g.cur_hp,keys=[g.red_key,g.green_key,g.blue_key])
Path(sys.argv[2]).write_text(json.dumps(result)+'\n');print({k:v for k,v in result.items() if k!='steps'})
