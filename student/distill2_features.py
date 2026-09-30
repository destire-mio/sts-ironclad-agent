"""Public feature contract; no teacher, simulator copies, RNG, or afterstates."""
from functools import lru_cache
import hashlib
import json
import numpy as np
from distill2_base import schema_from_runtime as base_schema, public_extra

ROOMS = ('MONSTER', 'ELITE', 'REST', 'SHOP', 'EVENT', 'TREASURE', 'BOSS')
EXTRA_NAMES = ['hp_fraction','missing_hp/100','deck_size/40','gold/300','map_y/15',
               'act/4','selection_count/5','potion_count/5', 'potion_capacity/5',
               'strike_count/10','defend_count/10','upgraded_count/40',
               'attack_count/40','skill_count/40','power_count/40','curse_count/40',
               'removal_cost/300','red_key','green_key','blue_key']
ROUTE_NAMES = ['is_map','burning_here','burning_reachable','burning_distance/15',
               'reachable_nodes/105'] + ['nearest_'+r+'/15' for r in ROOMS] + [
               k+'_'+r+'/15' for k in ('path_min','path_max') for r in ROOMS]


def schema_from_runtime(x, parent):
    s = base_schema(x, parent)
    s.update(version=2, feature_version='distill2-public-v1', extra_names=EXTRA_NAMES,
             route_names=ROUTE_NAMES, context_dim=2*s['DESC_DIM'],
             offsets={k:int(getattr(x.A,k)) for k in dir(x.A) if k.startswith(('OFF_','W_'))},
             obs_encoder_sha256=hashlib.sha256(open(x.A.__file__, 'rb').read()).hexdigest(),
             public_mask='0:13,32:75,event 75:132,visible event amounts 22:27,map,deck/relic/potion tail,flame position; all other prefix zero')
    s['schema_id'] = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()
    return s


def public_observation(gc, A, schema):
    raw = np.asarray(A.obs_vec(gc), dtype=np.float32)
    if raw.shape != (schema['OBS_DIM'],):
        raise ValueError('observation shape drift')
    out = np.zeros_like(raw)
    out[:13] = raw[:13]
    out[32:75] = raw[32:75]  # keys, current/previous room, screen, public boss icon
    if gc.screen_state.name == 'EVENT_SCREEN':
        out[75:132] = raw[75:132]
        out[22:27] = raw[22:27]  # displayed event HP/gold amounts, never eventData
    out[schema['deck_offset']-805:] = raw[schema['deck_offset']-805:]
    return out


def visible_extra(gc):
    deck = list(gc.deck)
    names = [c.id.name for c in deck]
    types = [c.type.name for c in deck]
    return np.asarray(public_extra(gc) + [gc.potion_capacity/5,
        names.count('STRIKE_RED')/10, names.count('DEFEND_RED')/10,
        sum(c.upgrade_count > 0 for c in deck)/40,
        types.count('ATTACK')/40, types.count('SKILL')/40,
        types.count('POWER')/40, types.count('CURSE')/40,
        (gc.shop_remove_cost/300 if gc.screen_state.name == 'SHOP_ROOM' else 0),
        float(gc.red_key),float(gc.green_key),float(gc.blue_key)], dtype=np.float32)


def route_features(gc, actions):
    out = np.zeros((len(actions), len(ROUTE_NAMES)), dtype=np.float32)
    if gc.screen_state.name != 'MAP_SCREEN':
        return out
    # Use only public node kinds/edges and flame coordinates. Never read its buff.
    flame = tuple(int(v) for v in gc.burning_elite[:2])
    @lru_cache(None)
    def walk(x,y):
        room = 'BOSS' if y >= 15 else gc.map_node_room(x,y).name
        one = np.asarray([room == r for r in ROOMS], dtype=np.float32)
        children = [] if y >= 15 else list(gc.map_node_children(x,y))
        sub = [walk(int(cx),y+1) for cx in children]
        nodes = {(x,y)}
        for v in sub:
            nodes.update(v[0])
        lo = one + (np.min([v[1] for v in sub],axis=0) if sub else 0)
        hi = one + (np.max([v[2] for v in sub],axis=0) if sub else 0)
        return nodes, lo, hi
    for i,a in enumerate(actions):
        if a.is_potion_action:
            continue
        x,y = int(a.idx1), int(gc.cur_map_node_y)+1
        nodes,lo,hi = walk(x,y)
        nearest = [min([ny-y for nx,ny in nodes if
                       ('BOSS' if ny>=15 else gc.map_node_room(nx,ny).name)==r] or [16])/15
                   for r in ROOMS]
        reachable = flame in nodes
        out[i] = [1,float(flame==(x,y)),float(reachable),
                  (flame[1]-y)/15 if reachable else 16/15,len(nodes)/105] + nearest + list(lo/15)+list(hi/15)
    return out


def candidate_context(descriptors):
    d = np.asarray(descriptors, dtype=np.float32)
    # Mean and max retain candidate identities, prices and action kinds.
    return np.concatenate([d.mean(axis=0,dtype=np.float32),d.max(axis=0)])


def public_packet(gc, actions, descriptors, schema, encoder=None):
    if isinstance(gc, dict):
        p = gc
    else:
        if encoder is None:
            import armG_train as encoder
        p = dict(schema_id=schema['schema_id'], observation=public_observation(gc,encoder,schema),
                 extra=visible_extra(gc), routes=route_features(gc,actions))
    n = len(actions)
    if not n or len(descriptors) != n or p.get('schema_id') != schema['schema_id']:
        raise ValueError('empty/misaligned candidates or feature schema drift')
    sizes = {'observation':(schema['OBS_DIM'],),'extra':(len(EXTRA_NAMES),),
             'routes':(n,len(ROUTE_NAMES))}
    result = {'schema_id':schema['schema_id']}
    for k,shape in sizes.items():
        v = np.asarray(p[k],dtype=np.float32)
        if v.shape != shape or not np.isfinite(v).all():
            raise ValueError('invalid public packet '+k)
        result[k] = v
    d = np.asarray(descriptors,dtype=np.float32)
    if d.shape != (n,schema['DESC_DIM']) or not np.isfinite(d).all():
        raise ValueError('invalid descriptors')
    result['descriptors'] = d
    result['context'] = candidate_context(d)
    result['bits'] = [int(a if isinstance(a,int) else a.bits) for a in actions]
    if len(set(result['bits'])) != n:
        raise ValueError('duplicate action bits')
    return result
