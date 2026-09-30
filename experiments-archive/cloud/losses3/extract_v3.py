import os,sys,json,gzip,glob,time,hashlib,traceback,collections
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import p300_common as C
S=C.sts
OUT=Path(os.path.expanduser('~/sts/runs/losses3'))
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

def one(path):
    started=time.monotonic();r=json.load(gzip.open(path,'rt'));seed=r['seed']
    try:
        g=S.GameContext(S.CharacterClass.IRONCLAD,seed,20);steps=[];invalid=[];mismatch=[];bosses=[];battle_n=0
        for idx,row in enumerate(r['prefix']):
            C.H.clock_input(g,C.CONFIG)
            b=snap(g); rec={'index':idx,'before':b,'kind':row['kind']}
            if row['kind']=='battle':
                assert g.screen_state==S.ScreenState.BATTLE,(idx,g.screen_state)
                bc=S.BattleContext();bc.init(g);used=[];discarded=[];detail=[]
                for bits in row['actions']:
                    a=S.SearchAction.from_bits(bits&0xffffffff)
                    if not a.is_valid(bc): invalid.append([idx, len(detail), repr(a)])
                    if True: detail.append(dict(bits=int(bits), action=repr(a), state=repr(bc)))
                    if a.action_type==S.SearchActionType.POTION:
                        # Binding target 8191 is the encoded -1 discard; record raw target and item.
                        it=dict(bits=int(bits),repr=repr(a))
                        try:it['potions']=[potion(x) for x in bc.potions]
                        except:pass
                        used.append(it)
                    a.execute(bc)
                if int(bc.outcome)!=row['outcome']:mismatch.append(['battle_outcome',idx,int(bc.outcome),row['outcome']])
                bc.exit_battle(g);battle_n+=1
                rec.update(outcome=int(bc.outcome),actions=len(row['actions']),potion_actions=used,final_battle=repr(bc),combat_detail=detail,search=row.get('search',{}))
                enc=b['encounter']
                rec['battle_type']='heart' if enc=='THE_HEART' else 'spear' if enc=='SHIELD_AND_SPEAR' else 'boss' if C.F.is_boss(int(S.MonsterEncounter.__members__[enc])) else 'elite' if enc in ('GREMLIN_NOB','LAGAVULIN','THREE_SENTRIES','GREMLIN_LEADER','SLAVERS','BOOK_OF_STABBING','GIANT_HEAD','NEMESIS','REPTOMANCER') else 'hall'
                if C.F.is_boss(int(S.MonsterEncounter.__members__[enc])):
                    bosses.append(dict(floor=b['floor'],act=b['act'],hp=b['hp'],max_hp=b['max_hp'],encounter=enc,deck=len(b['deck']),relics=len(b['relics']),potions=b['potion_count'],won=g.outcome!=S.GameOutcome.PLAYER_LOSS,hp_after=int(g.cur_hp)))
            else:
                acts=list(S.get_legal_game_actions(g));a=S.GameAction(row['action']&0xffffffff)
                if int(a.bits) not in [int(v.bits) for v in acts]:invalid.append(idx)
                rec['chosen']=action_info(g,a);rec['options']=[action_info(g,x) for x in acts]
                rec['guide_audit']=row.get('guide_audit',{}); rec['sv_audit']=row.get('sv_audit',{})
                if g.screen_state==S.ScreenState.REWARDS:
                    rr=g.rewards;rec['reward_potions']=[potion(p) for p in rr['potions']];rec['reward_cards']=[[card(c) for c in group] for group in rr['cards']]
                a.execute(g)
            after=snap(g)
            rec['after']={k:after[k] for k in ('hp','max_hp','gold','potion_count','potions','keys','screen','floor','act')}
            cb,ca=collections.Counter(b['deck']),collections.Counter(after['deck'])
            rec['added']=list((ca-cb).elements());rec['removed']=list((cb-ca).elements());rec['relic_added']=list((collections.Counter(after['relics'])-collections.Counter(b['relics'])).elements())
            steps.append(rec)
        terminal=C.H.terminal(g)
        for k,actual in [('status',terminal),('floor',int(g.floor_num)),('act',int(g.act))]:
            if r[k]!=actual:mismatch.append([k,actual,r[k]])
        if bosses!=r['bosses']:mismatch.append(['bosses',bosses,r['bosses']])
        out=dict(seed=seed,status=terminal,recorded_status=r['status'],arm=r['arm'],act=int(g.act),floor=int(g.floor_num),terminal=snap(g),invalid=invalid,mismatch=mismatch,steps=steps,source=str(path),source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),seconds=time.monotonic()-started)
        with gzip.open(OUT/'replayed'/f'{seed}.json.gz','wt') as f:json.dump(out,f,separators=(',',':'))
        return {k:v for k,v in out.items() if k not in ('steps',)}
    except Exception:return dict(seed=seed,error=traceback.format_exc(),source=str(path))

