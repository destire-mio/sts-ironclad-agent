"""State comparison only: no model scoring, search budget, or value-table rules.

The codec supplies card/relic/potion ID translation shared with state import.
A comparison always happens before authoritative state is imported again.
"""
from sim_patch.parity.core import differences
from sim_patch.parity.adapter import rng_bits

def projection(codec):
    g=codec.gc
    return dict(seed=g.seed,ascension=g.ascension,act=g.act,floor=g.floor_num,
        hp=g.cur_hp,max_hp=g.max_hp,gold=g.gold,
        card_rarity_factor=g.card_rarity_factor,potion_chance=g.potion_chance,
        deck=[dict(id=c.id.name,upgrades=c.upgrade_count,misc=c.misc,bottled=i in g.bottle_indices) for i,c in enumerate(g.deck)],
        relics=[dict(id=r.id.name,counter=r.data) for r in g.relics],potions=[int(p) for p in g.potions[:g.potion_capacity]],
        keys=[g.red_key,g.green_key,g.blue_key],rng=codec.native.run_rng(g))

def compare(codec, view, before):
    predicted=projection(codec);g=view['game'];r=view['live_run']
    truth=dict(seed=g['seed'],ascension=g['ascension_level'],act=g['act'],floor=g['floor'],
        hp=g['current_hp'],max_hp=g['max_hp'],gold=g['gold'],
        card_rarity_factor=r['card_rarity_factor'],potion_chance=r['potion_chance'],
        deck=[dict(id=codec.card(c).id.name,upgrades=c['upgrades'],misc=codec.card(c).misc,bottled=c['bottled']) for c in r['deck']],
        relics=[dict(id=codec.relic(c['id']).name,counter=codec.relic_counter(c)) for c in g['relics']],
        potions=[int(codec.potion(c['id'])) for c in g['potions']],keys=[view['ruby'],view['emerald'],view['sapphire']],
        rng={k:rng_bits(v) for k,v in view['rng'].items() if k!='mapRng'})
    raw=g['full_rng_state']['streams']['NeowEvent.rng']
    if raw['initialized']:truth['rng']['neowRng']=rng_bits(raw)
    # The simulator cannot predict all shared RNG consumption. These sources
    # remain in every raw snapshot and have a separate original/SL audit.
    predicted['rng'].pop('mathUtilRng',None)
    def reward_values(rows):
        return dict(gold=list(rows['gold']),relics=[int(v) for v in rows['relics']],
                    potions=[int(v) for v in rows['potions']],emerald=rows['emerald'],sapphire=rows['sapphire'],
                    cards=[[(int(c.id),c.upgrade_count,c.misc) for c in group] for group in rows['cards']])
    screens={'EVENT':'EVENT_SCREEN','MAP':'MAP_SCREEN','REST':'REST_ROOM','SHOP_SCREEN':'SHOP_ROOM',
        'COMBAT_REWARD':'REWARDS','CARD_REWARD':'REWARDS','BOSS_REWARD':'BOSS_RELIC_REWARDS',
        'CHEST':'TREASURE_ROOM','GRID':'CARD_SELECT'}
    if g['current_hp']>0 and g['screen_type'] in screens:
        truth['screen']=screens[g['screen_type']];predicted['screen']=codec.gc.screen_state.name
    if g['screen_type'] in ('COMBAT_REWARD','CARD_REWARD'):
        truth['rewards']=reward_values(codec.rewards(r['rewards']))
        predicted['rewards']=reward_values(codec.gc.rewards) if codec.gc.screen_state==codec.sts.ScreenState.REWARDS else None
    if g['screen_type']=='BOSS_REWARD':
        truth['boss_relics']=[int(codec.relic(v['id'])) for v in g['screen_state']['relics']]
        predicted['boss_relics']=[int(v) for v in codec.gc.boss_relics] if codec.gc.screen_state==codec.sts.ScreenState.BOSS_RELIC_REWARDS else None
    if g['screen_type']=='MAP' and codec.gc.screen_state==codec.sts.ScreenState.MAP_SCREEN:
        room_names={'M':'MONSTER','E':'ELITE','R':'REST','$':'SHOP','?':'EVENT','T':'TREASURE','B':'BOSS'}
        truth['map']=[];predicted['map']=[]
        for n in g['map']:
            if n['y']>=15:continue
            truth['map'].append((n['x'],n['y'],room_names[n['symbol']],sorted(c['x'] for c in n.get('children',[]) if c['y']<15)))
            predicted['map'].append((n['x'],n['y'],codec.gc.map_node_room(n['x'],n['y']).name,
                                     sorted(codec.gc.map_node_children(n['x'],n['y']))))
    diff=differences(truth,predicted,'/run')
    return dict(differences=diff,expected=truth,actual=predicted,
                compared_fields=sorted(truth),
                gaps=['shared_MathUtils_and_Collections_prediction','mapRng_has_no_persistent_native_counter',
                      'event_private_fields_and_remaining_pools_not_predicted'])
