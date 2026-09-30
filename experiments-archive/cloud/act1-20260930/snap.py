import os,sys,json,gzip,glob,time,hashlib,traceback,collections
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import p300_common as C
S=C.sts
OUT=Path(__file__).resolve().parent
AOE=set('CLEAVE WHIRLWIND IMMOLATE THUNDERCLAP REAPER COMBUST SHOCKWAVE CORPSE_EXPLOSION'.split())
BLOCK=set('DEFEND_RED SHRUG_IT_OFF IRON_WAVE TRUE_GRIT FLAME_BARRIER GHOSTLY_ARMOR POWER_THROUGH SECOND_WIND IMPERVIOUS ENTRENCH METALLICIZE FEEL_NO_PAIN RAGE DISARM SHOCKWAVE'.split())
DRAW=set('POMMEL_STRIKE SHRUG_IT_OFF BATTLE_TRANCE BURNING_PACT DARK_EMBRACE OFFERING EVOLVE BRUTALITY INFLAME_NO SWORD_BOOMERANG_NO FLASH_OF_STEEL FINESSE MASTER_OF_STRATEGY DEEP_BREATH'.split())
SCALE=set('INFLAME DEMON_FORM SPOT_WEAKNESS LIMIT_BREAK BARRICADE ENTRENCH FEEL_NO_PAIN DARK_EMBRACE RAMPAGE SEARING_BLOW'.split())
REST=['REST','SMITH','RECALL','LIFT','TOKE','DIG','LEAVE']
def name(x):
    return x.name if hasattr(x,'name') else str(x)
def card(c):return c.id.name+'+'*int(c.upgrade_count)
def potion(p):
    try:return S.PotionId(int(p)).name
    except:return str(p)
def relic(r):
    try:return S.RelicId(int(r)).name
    except:return str(r)
def snap(g):
    cards=list(g.deck); ids=[c.id.name for c in cards]
    return dict(act=int(g.act),floor=int(g.floor_num),screen=g.screen_state.name,room=g.cur_room.name,event=g.event_id_string,event_data=int(g.event_data),event_phase=int(g.event_phase),hp=int(g.cur_hp),max_hp=int(g.max_hp),gold=int(g.gold),deck=[card(c) for c in cards],relics=[relic(r.id) for r in g.relics],potions=[potion(p) for p in g.potions],potion_count=int(g.potion_count),potion_capacity=int(g.potion_capacity),keys=[bool(g.red_key),bool(g.green_key),bool(g.blue_key)],x=int(g.cur_map_node_x),y=int(g.cur_map_node_y),burning=list(g.burning_elite),boss=g.boss.name,encounter=g.encounter.name,remove_cost=int(g.shop_remove_cost),shop_removes=int(g.shop_remove_count),features=dict(n=len(cards),attack=sum(c.type==S.CardType.ATTACK for c in cards),block=sum(x in BLOCK for x in ids),aoe=sum(x in AOE for x in ids),draw=sum(x in DRAW for x in ids),scale=sum(x in SCALE for x in ids),upgraded=sum(bool(c.upgraded) for c in cards),upgrade_levels=sum(int(c.upgrade_count) for c in cards),starter=sum(c.is_starter_strike_or_defend for c in cards),curses=sum(c.type==S.CardType.CURSE and c.id.name!='ASCENDERS_BANE' for c in cards)))
def action_info(g,a):
    d=dict(bits=int(a.bits),i=int(a.idx1),j=int(a.idx2))
    sc=g.screen_state.name; i=d['i'];j=d['j']
    if a.is_potion_action:
        d.update(kind='POTION_DISCARD' if a.is_potion_discard else 'POTION_DRINK',item=potion(g.potions[i]));return d
    if sc=='MAP_SCREEN':
        y=int(g.cur_map_node_y)+1
        d.update(kind='MAP',item=g.map_node_room(i,y).name if y<15 else 'BOSS',y=y,flame=(i,y)==tuple(g.burning_elite[:2]))
    elif sc=='REST_ROOM':d.update(kind='REST',item=REST[i] if i<len(REST) else str(i))
    elif sc=='EVENT_SCREEN':
        d.update(kind='EVENT',item=g.event_id_string,phase=int(g.event_phase),data=int(g.event_data))
        if g.event_id_string=='NEOW':d['option']=list(g.neow_options[i])
    elif sc=='REWARDS':
        rt=a.rewards_action_type.name;d['kind']='REWARD_'+rt;r=g.rewards
        if rt=='CARD':d['item']=card(r['cards'][i][j]) if j!=5 else 'SINGING_BOWL'
        elif rt=='RELIC':d['item']=relic(r['relics'][i])
        elif rt=='POTION':d['item']=potion(r['potions'][i])
        elif rt=='GOLD':d['item']=int(r['gold'][i])
        elif rt=='KEY':d['item']='BLUE' if r['sapphire'] else 'GREEN'
    elif sc=='SHOP_ROOM':
        rt=a.rewards_action_type.name;d['kind']='SHOP_'+rt
        if rt in ('CARD','RELIC','POTION'):
            x,price={'CARD':g.get_shop_cards,'RELIC':g.get_shop_relics,'POTION':g.get_shop_potions}[rt]()[i]
            d['item']={'CARD':card,'RELIC':relic,'POTION':potion}[rt](x);d['price']=int(price)
        elif rt=='CARD_REMOVE':d['price']=int(g.shop_remove_cost)
    elif sc=='BOSS_RELIC_REWARDS':d.update(kind='BOSS_RELIC',item='SKIP' if i==3 else relic(g.boss_relics[i]))
    elif sc=='CARD_SELECT':
        d.update(kind='SELECT',selection_type=int(g.selection_type),selection_count=int(g.selection_count))
        d['item']='CANCEL' if a.rewards_action_type==S.RewardsActionType.SKIP else card(g.selection_cards[i])
    elif sc=='TREASURE_ROOM':d.update(kind='TREASURE',item='OPEN' if i==0 else 'LEAVE')
    else:d['kind']=sc
    return d
