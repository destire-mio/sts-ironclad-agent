"""Guide v2: public-information ports, then bounded counterfactual fights.

Call guide_choice2(x, gc, actions, descriptors, chosen, parent, cache) and
(optionally) guide_route2(..., chosen, parent, cache). Supply ONE fresh dict per
whole run, shared by both hooks; never share it across games or processes.
No integration changes are required here. cache['guide2']['stats'/'decisions']
are JSON-serializable diagnostics; inspect public port_profile(gc) as well.

Sources: guide5/guide.txt PDF pp4-7 (ports, ~180 Heart opening defence,
cycle total S, card slots T, V=K*S/T); pp10-12 (exhaust/startup); pp19-21
(elites). Per-card page references are inherited from guide_rules.CARD_RULES.
ALL coefficients, targets, weights and thresholds below are engineering
hypotheses, not measured game damage, calibrated probabilities or guide quotes.
Native low-budget fights are probes, not a substitute for held-out whole runs.

RNG contract: copy_game is an opaque value copy, never a prediction from live
RNG. No card/relic candidate executes a GameAction. Potion purchases execute only
without Courier, after verifying that they cannot restock. Before
simulate the copy's seed, floor, act and room are replaced with fixed panel
values. fightsim resets misc/potion RNG with the nonzero fixed evaluation seed;
BattleContext derives its other four streams from seed+floor. We never inspect
live RNG, except the caller runtime's fingerprint for an equality audit.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from math import sqrt
import time
from types import SimpleNamespace

import guide_rules as G

@lru_cache(maxsize=1024)
def _name(value):
    # Pybind enum.name and repr are expensive; v1 repeatedly asks for both.
    name=getattr(value,'name',None)
    return name if name is not None else str(value).rsplit('.',1)[-1]


class _PublicView:
    """Read-only Python card/relic metadata for v1 math; native game stays opaque.

    This changes representation, not rules. The full v1 DeckProfile is checked
    against native inputs in the regression suite. Native simulation/actions
    always receive the original GameContext or its value copy, never this view.
    """
    def __init__(self,gc):
        self._gc=gc
        self.deck=[SimpleNamespace(id=_name(c.id),type=_name(c.type),
                   upgraded=bool(c.upgraded),upgrade_count=int(c.upgrade_count),
                   upgradable=bool(c.upgradable),transformable=bool(c.transformable),misc=int(c.misc),
                   is_strikeCard=bool(c.is_strikeCard)) for c in gc.deck]
        self.relics=[SimpleNamespace(id=_name(r.id),data=int(r.data)) for r in gc.relics]

    def __getattr__(self,name):
        return getattr(self._gc,name)


def _public_view(gc):
    return gc if isinstance(gc,_PublicView) else _PublicView(gc)


SEEDS = (901, 902, 903, 904)
SIMULATIONS = 128
CPU_LIMIT = 24.0  # seconds of extra CPU, includes Python/fingerprints/copying
ACT_CPU_LIMITS = (6.0, 12.0, 20.0, CPU_LIMIT)
MAX_FIGHTS = 3200

# Every red card, including starter cards, has base AND upgraded numeric rows.
# Raw units: damage/block per use, strength, strength hit multiplier, debuff
# turns, cards drawn/exhausted, energy, recurring block, retained block fraction.
# Zero means no *direct* supply, not no value. Conditional engines are resolved
# by card_contribution using the current public deck, never an imagined combo.
_SPECIAL = {
    'ANGER': {'energy': (.5,.5), 'clutter': (.5,.5)},
    'ARMAMENTS': {'upgrade': (1,3)}, 'BASH': {'vuln': (2,3)},
    'BATTLE_TRANCE': {'draw': (3,4)}, 'BARRICADE': {'retain': (.8,.8)},
    'BERSERK': {'energy': (1.2,1.6), 'risk': (8,4)},
    'BLOOD_FOR_BLOOD': {'damage': (18,22)},
    'BLOODLETTING': {'energy': (2,3), 'risk': (3,3)},
    'BODY_SLAM': {'body': (1,1)}, 'BRUTALITY': {'draw': (1.5,2), 'risk': (2,2)},
    'BURNING_PACT': {'draw': (2,3), 'exhaust': (1,1)},
    'CLEAVE': {'aoe': (8,11)}, 'CLOTHESLINE': {'weak': (2,3)},
    'COMBUST': {'damage': (10,14), 'aoe': (10,14), 'risk': (2,2)},
    'CORRUPTION': {'corruption': (1,1)},
    'DARK_EMBRACE': {'embrace': (1,1)}, 'DEMON_FORM': {'strength': (6,9)},
    'DISARM': {'disarm': (2,3)}, 'DOUBLE_TAP': {'copies': (1,2)},
    'DROPKICK': {'conditional_draw': (1,1), 'conditional_energy': (1,1)},
    'DUAL_WIELD': {'copies': (.5,1)}, 'ENTRENCH': {'entrench': (1,1)},
    'EVOLVE': {'evolve': (1,2)}, 'EXHUME': {'retrieve': (1,1)},
    'FEED': {'maxhp': (3,4)}, 'FEEL_NO_PAIN': {'fnp': (3,4)},
    'FIEND_FIRE': {'damage': (21,30), 'hits': (3,3), 'exhaust': (3,3)},
    'FIRE_BREATHING': {'fire': (6,10)},
    'FLAME_BARRIER': {'thorns': (4,6)}, 'FLEX': {'temp_strength': (2,4)},
    'GHOSTLY_ARMOR': {}, 'HAVOC': {'exhaust': (.7,1), 'energy': (.3,1)},
    'HEADBUTT': {'control': (.4,.4)}, 'HEAVY_BLADE': {'hits': (3,5)},
    'HEMOKINESIS': {'risk': (2,2)}, 'IMMOLATE': {'aoe': (21,28), 'clutter': (1,1)},
    'INFERNAL_BLADE': {'damage': (11,11), 'energy': (.4,1)},
    'INFLAME': {'strength': (2,3)}, 'INTIMIDATE': {'weak': (1,2)},
    'JUGGERNAUT': {'juggernaut': (5,7)}, 'LIMIT_BREAK': {'limit': (1,1.5)},
    'METALLICIZE': {'persistent': (3,4)}, 'OFFERING': {'draw': (3,5), 'energy': (2,2), 'risk': (6,6)},
    'PERFECTED_STRIKE': {'perfected': (2,3)}, 'POMMEL_STRIKE': {'draw': (1,2)},
    'POWER_THROUGH': {'clutter': (2,2)}, 'PUMMEL': {'hits': (4,5)},
    'RAGE': {'rage': (3,5)}, 'RAMPAGE': {'rampage': (5,8)},
    'REAPER': {'aoe': (4,5), 'reaper': (1,1)},
    'RECKLESS_CHARGE': {'clutter': (1,1)}, 'RUPTURE': {'rupture': (1,2)},
    'SEARING_BLOW': {}, 'SECOND_WIND': {'second_wind': (5,7), 'exhaust': (2,2)},
    'SEEING_RED': {'energy': (1,2)}, 'SENTINEL': {'sentinel': (2,3)},
    'SEVER_SOUL': {'exhaust': (2,2)}, 'SHOCKWAVE': {'vuln': (3,5), 'weak': (3,5)},
    'SHRUG_IT_OFF': {'draw': (1,1)}, 'SPOT_WEAKNESS': {'strength': (2.1,2.8)},
    'SWORD_BOOMERANG': {'hits': (3,4)}, 'THUNDERCLAP': {'vuln': (1,1), 'aoe': (4,7)},
    'TRUE_GRIT': {'exhaust': (.7,1)}, 'TWIN_STRIKE': {'hits': (2,2)},
    'WARCRY': {'draw': (0,1), 'control': (.2,.5)},
    'WHIRLWIND': {'damage': (15,24), 'aoe': (15,24), 'hits': (3,3)},
    'WILD_STRIKE': {'clutter': (1,1)},
}
_ZERO = set('ANGER BATTLE_TRANCE BLOODLETTING FLEX INTIMIDATE OFFERING RAGE RECKLESS_CHARGE WARCRY'.split())
_THREE = set('BARRICADE BLUDGEON CORRUPTION DEMON_FORM'.split())
_TWO = set('BASH BLOOD_FOR_BLOOD CARNAGE CLOTHESLINE DOUBLE_TAP ENTRENCH FIEND_FIRE FLAME_BARRIER HEAVY_BLADE IMMOLATE IMPERVIOUS REAPER SEVER_SOUL SHOCKWAVE UPPERCUT DARK_EMBRACE JUGGERNAUT'.split())
_COST_UP = set('BARRICADE BLOOD_FOR_BLOOD BODY_SLAM CORRUPTION DARK_EMBRACE ENTRENCH HAVOC INFERNAL_BLADE SEEING_RED'.split())
_POWER = set('BARRICADE BERSERK BRUTALITY COMBUST CORRUPTION DARK_EMBRACE DEMON_FORM EVOLVE FEEL_NO_PAIN FIRE_BREATHING INFLAME JUGGERNAUT METALLICIZE RUPTURE'.split())

def _card_table():
    rows = {}
    for name, rule in G.CARD_RULES.items():
        cost = 0 if name in _ZERO else 3 if name in _THREE else 2 if name in _TWO else 1
        if name == 'BERSERK': cost = 0
        if name == 'BLOOD_FOR_BLOOD': cost = 3  # effective cost after one HP loss
        if name == 'WHIRLWIND': cost = 3
        features = dict(damage=G._DAMAGE.get(name,(0,0)), block=G._BLOCK.get(name,(0,0)),
                        cost=(cost,max(0,cost-(name in _COST_UP))), power=(int(name in _POWER),)*2)
        if features['damage'][0]: features['hits'] = (1,1)
        features.update(_SPECIAL.get(name,{}))
        if name == 'UPPERCUT': features.update(vuln=(1,2),weak=(1,2))
        rows[name] = {'page': rule.page, 'base': {k:float(v[0]) for k,v in features.items()},
                      'upgrade': {k:float(v[1]) for k,v in features.items()}}
    return rows

CARD_PORTS = _card_table()

# Public relic text converted to discounted per-cycle/three-turn proxy supply.
# No random-on-acquire relic (Astrolabe, Pandora, Orrery, etc.) is simulated.
RELIC_PORTS = {
    'BURNING_BLOOD': {'healing':6}, 'BLACK_BLOOD': {'healing':12},
    'VAJRA': {'strength':1}, 'ODDLY_SMOOTH_STONE': {'dex':1},
    'ANCHOR': {'block':10}, 'HORN_CLEAT': {'block':14}, 'CAPTAINS_WHEEL': {'block':18},
    'BAG_OF_PREPARATION': {'draw':2}, 'BAG_OF_MARBLES': {'vuln':1},
    'LANTERN': {'energy':1}, 'HAPPY_FLOWER': {'energy':1}, 'ANCIENT_TEA_SET': {'energy':1},
    'SUNDIAL': {'energy':1}, 'RUNIC_PYRAMID': {'control':2}, 'SNECKO_EYE': {'draw':4},
    'CALIPERS': {'retain':.5}, 'THE_ABACUS': {'block':6},
    'ORICHALCUM': {'persistent':3}, 'THREAD_AND_NEEDLE': {'block':12},
    'TORII': {'heart_multi':18}, 'TUNGSTEN_ROD': {'heart_multi':15},
    'INCENSE_BURNER': {'burst':30}, 'FOSSILIZED_HELIX': {'burst':22},
    'PAPER_PHROG': {'vuln':1}, 'PAPER_KRANE': {'weak':1},
    'PEN_NIB': {'damage':8}, 'AKABEKO': {'damage':8}, 'GREMLIN_HORN': {'draw':1},
    'KUNAI': {'dex':.7}, 'SHURIKEN': {'strength':1}, 'ORNAMENTAL_FAN': {'block':4},
    'MUMMIFIED_HAND': {'energy':1}, 'DEAD_BRANCH': {'draw':2},
    'MEDICAL_KIT': {'exhaust':1}, 'BLUE_CANDLE': {'exhaust':.5},
    'CHEMICAL_X': {'chemical':2}, 'TOXIC_EGG': {'upgrade':2},
    'MOLTEN_EGG': {'upgrade':1}, 'FROZEN_EGG': {'upgrade':.5},
    'MEAT_ON_THE_BONE': {'healing':6}, 'BLOOD_VIAL': {'healing':2},
    'SELF_FORMING_CLAY': {'block':6}, 'RED_SKULL': {'strength':1.5},
    'GIRYA': {}, 'ICE_CREAM': {'energy':1}, 'CHARONS_ASHES': {'damage':6,'aoe':6},
    'CHAMPION_BELT': {'weak':1}, 'ORANGE_PELLETS': {'burst':8},
    'BRONZE_SCALES': {'thorns':3}, 'CENTENNIAL_PUZZLE': {'draw':1.5},
}
for _r in G._ENERGY_RELICS:
    RELIC_PORTS[_r] = {'energy':3}  # per cycle, converted to energy/turn below

POTION_PORTS = {
    'FIRE_POTION': {'damage':20}, 'EXPLOSIVE_POTION': {'damage':10,'aoe':10},
    'BLOCK_POTION': {'block':12}, 'STRENGTH_POTION': {'strength':2},
    'DEXTERITY_POTION': {'dex':2}, 'ENERGY_POTION': {'energy':2},
    'SWIFT_POTION': {'draw':3}, 'FEAR_POTION': {'vuln':3}, 'WEAK_POTION': {'weak':3},
    'FLEX_POTION': {'temp_strength':5}, 'SPEED_POTION': {'block':15},
    'ANCIENT_POTION': {'burst':8}, 'ESSENCE_OF_STEEL': {'block':10},
    'LIQUID_BRONZE': {'thorns':3}, 'HEART_OF_IRON': {'block':30},
    'GHOST_IN_A_JAR': {'burst':40}, 'FAIRY_POTION': {'healing':24},
    'BLOOD_POTION': {'healing':15}, 'REGEN_POTION': {'healing':12},
    'LIQUID_MEMORIES': {'draw':2,'energy':2}, 'DUPLICATION_POTION': {'damage':15,'block':8},
    'GAMBLERS_BREW': {'draw':3}, 'SNECKO_OIL': {'draw':3,'energy':1},
    'ELIXIR_POTION': {'exhaust':3}, 'CULTIST_POTION': {'strength':3},
    'BLESSING_OF_THE_FORGE': {'upgrade':3}, 'FRUIT_JUICE': {'healing':5},
    'ATTACK_POTION': {'damage':10}, 'SKILL_POTION': {'block':8},
    'POWER_POTION': {'strength':1,'persistent':2}, 'COLORLESS_POTION': {'draw':1},
    'DISTILLED_CHAOS': {'damage':10,'block':5}, 'ENTROPIC_BREW': {'burst':10},
    'SMOKE_BOMB': {},
}

PORTS = ('cycle_attack','growth_attack','aoe','burst_defense','sustain_defense',
         'draw','energy','exhaust','heart_multi','retention','time_eater',
         'awakened','race','boss')
# Main ports p4-7; threat-specific demands are engineering assumptions.
_TARGET_ROWS = (
    (50,8,12,45,10,6,3.4,1.5,0,0,0,0,22,22),
    (80,24,24,90,20,7,4,3,12,10,0,0,34,34),
    (105,45,30,135,30,8,4.5,5,25,20,0,0,44,44),
    (115,60,24,180,38,8,4.5,5,40,30,0,0,48,48),
)
PORT_WEIGHTS = dict(zip(PORTS,(1,.8,.65,1.3,.9,.7,.65,.65,.5,.25,.6,.6,1,.65)))
ELITES = {1:('GREMLIN_NOB','LAGAVULIN','THREE_SENTRIES'),
          2:('GREMLIN_LEADER','SLAVERS','BOOK_OF_STABBING'),
          3:('GIANT_HEAD','NEMESIS','REPTOMANCER')}


def port_targets(gc):
    t = dict(zip(PORTS,_TARGET_ROWS[min(4,max(1,int(gc.act)))-1]))
    boss = _name(gc.boss) if int(gc.act) <= 3 else 'THE_HEART'
    changes = {
        'HEXAGHOST': {'growth_attack':14,'burst_defense':55},
        'SLIME_BOSS': {'race':30,'aoe':20},
        'THE_GUARDIAN': {'sustain_defense':15},
        'CHAMP': {'growth_attack':38}, 'COLLECTOR': {'aoe':30},
        'AUTOMATON': {'burst_defense':110},
        'TIME_EATER': {'time_eater':13,'sustain_defense':35},
        'AWAKENED_ONE': {'awakened':40,'sustain_defense':35},
        'DONU_AND_DECA': {'race':52,'aoe':32},
    }
    t.update(changes.get(boss,{}))
    return t


@lru_cache(None)
def _potion_ids():
    import p300_common as C
    return {int(C.sts.potion_id_from_name(n)):n for n in POTION_PORTS}


def _potion_names(gc):
    ids = _potion_ids()
    return [ids[p] for p in map(int,gc.potions) if p in ids]


def card_contribution(card, gc, profile=None):
    """Numeric base/upgrade contribution after visible synergy prerequisites.

    Returns raw resources; port_profile converts their sum to the PORTS units.
    A card's marginal PORTS contribution is the after-minus-before profile,
    not a fixed additive grade (p4,6-7,10-12).
    """
    name = G._cid(card)
    if name not in CARD_PORTS: return {}
    if profile is None: gc=_public_view(gc)
    p = profile or G.deck_profile(gc)
    c, up = p.counts, bool(card.upgraded)
    f = CARD_PORTS[name]['upgrade' if up else 'base'].copy()
    if name == 'SEARING_BLOW':
        k = int(card.upgrade_count); f['damage'] = 12+4*k+k*(k-1)/2
    if name == 'PERFECTED_STRIKE':
        f['damage'] = 6+(3 if up else 2)*sum(bool(k.is_strikeCard) for k in gc.deck)
    if name == 'CLASH': f['damage'] *= .4
    if name == 'BODY_SLAM': f['damage'] = min(40,p.burst_block)*.65
    if name == 'DROPKICK' and (c['BASH'] or c['SHOCKWAVE'] or c['THUNDERCLAP'] or c['UPPERCUT']):
        f.update(draw=.8,energy=.8)
    if name == 'CORRUPTION': f.update(energy=min(7,p.skills*.55),exhaust=min(6,p.skills*.5))
    if name == 'DARK_EMBRACE': f['draw'] = min(8,p.burn*.7)
    if name == 'FEEL_NO_PAIN': f['block'] = f['fnp']*min(6,p.burn)*.75
    if name == 'SECOND_WIND': f['block'] = f['second_wind']*min(3,max(0,p.skills-1)*.4)
    if name == 'SENTINEL': f['energy'] = f['sentinel']*min(1,p.burn/3)
    if name == 'ENTRENCH': f['block'] = p.burst_block*(.8 if c['BARRICADE'] or 'CALIPERS' in p.relics else .25)
    if name == 'LIMIT_BREAK': f['strength'] = p.strength*(1.2 if up and not c['CORRUPTION'] else .6)
    if name == 'RUPTURE': f['strength'] = f['rupture']*min(3,c['BRUTALITY']+c['BLOODLETTING']+c['HEMOKINESIS'])
    if name == 'RAGE': f['block'] = f['rage']*min(3,p.attacks/3)
    if name == 'REAPER': f['healing'] = min(25,(4+p.strength)*1.3)
    if name == 'EVOLVE': f['draw'] = f['evolve']*min(3,c['POWER_THROUGH']*2+c['WILD_STRIKE']+c['IMMOLATE']+c['RECKLESS_CHARGE'])
    if name == 'FIRE_BREATHING': f['aoe'] = f['fire']*min(3,c['POWER_THROUGH']+c['EVOLVE']*.5)
    if name == 'JUGGERNAUT': f['damage'] = f['juggernaut']*min(5,1+c['FEEL_NO_PAIN']*p.burn*.5)
    if name == 'RAMPAGE': f['damage'] += f['rampage']*min(2,10/max(5,p.size-p.burn))
    if name in {'DOUBLE_TAP','DUAL_WIELD'}:
        f['damage'] = f['copies']*min(25,max((G._DAMAGE.get(G._cid(k),(0,0))[bool(k.upgraded)] for k in gc.deck),default=0))*.5
    if name == 'EXHUME': f['block'] = 12*bool(c['IMPERVIOUS'] or c['OFFERING'] or c['FIEND_FIRE'])
    return f


@dataclass
class PortProfile:
    supply: dict
    targets: dict
    deficits: dict
    score: float
    S: float
    T: float
    K: float
    V: float
    pages: str = '4-7,10-12; card pages in CARD_PORTS'


def port_profile(gc):
    gc=_public_view(gc)
    p = G.deck_profile(gc)
    resources = Counter()
    for card in gc.deck: resources.update(card_contribution(card,gc,p))
    r = p.relics
    for relic in gc.relics:
        name = _name(relic.id)
        resources.update(RELIC_PORTS.get(name,{}))
        if name == 'GIRYA': resources['strength'] += max(0,int(relic.data))
    # Consumables are a discounted reserve, never persistent per-turn supply.
    for name in _potion_names(gc):
        for k,v in POTION_PORTS[name].items(): resources[k] += .4*v*(2 if 'SACRED_BARK' in r else 1)
    f = resources
    # Draw is summed per cycle. Exhaust reduces *later* T, with a capped credit.
    T = max(5,p.size + .65*f['clutter'] - min(p.size*.25,.5*f['exhaust']))
    draw = 5+min(5,5*f['draw']/max(10,p.size))+.25*f['control']
    energy = 3+f['energy']/max(2,p.size/5)
    playable=sum(_name(c.type) not in {'CURSE','STATUS'} for c in gc.deck)
    avg_cost = max(.7,f['cost']/max(1,playable))
    K = draw*min(1,energy/max(1,draw*.65*avg_cost))
    hits = f['hits']
    strength = f['strength']+.4*f['temp_strength']
    growth = strength*min(10,hits)+f['damage']*min(.45,.07*f['vuln'])
    S = f['damage']+.5*growth+f['upgrade']*2
    V = K*S/T
    block = f['block']+f['dex']*max(1,p.skills*.4)
    defense = K*block/T+f['persistent']+min(8,f['weak']*1.3)
    ready = min(1,draw*2/max(10,p.size))
    retained = min(1,f['retain'])*max(0,defense-12)*ready
    burst = 3*defense+f['burst']+f['disarm']*12+retained+min(12,f['healing']*.5)-f['risk']
    multi = f['disarm']*15+min(12,f['weak']*2)+f['heart_multi']
    aoe = f['aoe']+strength*min(3,sum(G._cid(k) in {'CLEAVE','WHIRLWIND','IMMOLATE','REAPER','THUNDERCLAP'} for k in gc.deck))
    if p.counts['WHIRLWIND']: aoe += f['chemical']*(8 if p.upgrades['WHIRLWIND'] else 5)
    played = max(1,min(draw,energy/avg_cost))
    supply = dict(cycle_attack=S,growth_attack=growth,aoe=aoe,burst_defense=max(0,burst),
                  sustain_defense=defense+retained*.5,draw=draw,energy=energy,exhaust=f['exhaust'],
                  heart_multi=multi,retention=retained,time_eater=(V+defense)/played,
                  awakened=max(0,V+defense*.4-2*f['power']),race=V+aoe*.2,boss=V+defense*.4)
    targets = port_targets(gc)
    deficits = {k:max(0,t-supply[k]) for k,t in targets.items()}
    # Squared deficit rewards filling the largest holes, saturating at target.
    score = -sum(PORT_WEIGHTS[k]*(deficits[k]/t)**2 for k,t in targets.items() if t>0)*10
    return PortProfile(supply,targets,deficits,score,S,T,K,V)


@dataclass
class Candidate:
    index: int
    game: object
    score: float
    label: str
    skip: bool = False
    detail: dict = field(default_factory=dict)
    target: int | None = None


def _state(cache):
    if cache is None: raise ValueError('guide_rules2 requires one cache dict per run')
    return cache.setdefault('guide2',dict(cpu=0.,origin_cpu=time.process_time(),max_fight_cpu=.02,fight_cost={},simulation_cpu=0.,memo={},decisions=[],stats=Counter()))


def _stat(state,key,n=1): state['stats'][key] += n


def _audit(x,gc,state,fn):
    start = time.process_time()
    before = x.R.fingerprint(gc)
    try: return fn()
    finally:
        after = x.R.fingerprint(gc)
        state['cpu'] += time.process_time()-start
        _stat(state,'fingerprints')
        if before != after:
            _stat(state,'fingerprint_failures')
            raise RuntimeError('guide2 mutated the main game fingerprint')


def _clone(gc):
    import p300_common as C
    g = C.F.copy_game(gc)
    g.seed = 0
    # Avoid accidentally applying the current live map's burning elite buff.
    g.cur_map_node_x = -99; g.cur_map_node_y = -99
    return g


def _copy_card(card):
    import p300_common as C
    out = C.sts.Card(card.id)
    for _ in range(int(card.upgrade_count)): out.upgrade()
    out.misc = card.misc
    return out


def _up(gc,index):
    import p300_common as C
    g = _clone(gc); C.F.upgrade_card(g,index); return g


def _remove(gc,index,price=0):
    g = _clone(gc); g.remove_card(index); g.gold = max(0,int(g.gold)-price); return g


def _add(gc,card,price=0):
    g = _clone(gc); g.obtain_card(_copy_card(card)); g.gold = max(0,int(g.gold)-price); return g


def _delta(before,after):
    return dict(fills={k:round(before.deficits[k]-after.deficits[k],3) for k in PORTS
                       if abs(before.deficits[k]-after.deficits[k])>.01},
                dV=round(after.V-before.V,3),dT=round(after.T-before.T,3))


def _candidates(x,gc,actions,kinds,chosen):
    import p300_common as C
    A = x.A; screen = _name(gc.screen_state); p = G.deck_profile(_public_view(gc))
    before = port_profile(gc); candidates = []; seen = {}
    def add(i,g,label,prior=0,price=0,skip=False,hp_value=0,target=None):
        q = port_profile(g)
        # Price competes with visible alternatives; HP changes matter at campfires.
        score = q.score-before.score+.28*prior-.025*price+hp_value
        c = Candidate(i,g,score,label,skip,_delta(before,q),target)
        if i not in seen or c.score>seen[i].score: seen[i]=c
    if screen == 'REWARDS':
        eligible = {A.AK_REWARD_CARD,A.AK_REWARD_SKIP,A.AK_REWARD_SINGING_BOWL}
        if kinds[chosen] not in eligible: return []
        rewards = gc.rewards; groups = rewards['cards']
        group = int(actions[chosen].idx1) if kinds[chosen] != A.AK_REWARD_SKIP else 0
        if len(groups)!=1 and kinds[chosen]==A.AK_REWARD_SKIP: return []
        if not 0<=group<len(groups): return []
        can_skip = len(groups)==1 and not any(rewards.get(k) for k in ('gold','relics','potions','emerald','sapphire'))
        for i,a in enumerate(actions):
            k = kinds[i]
            if k == A.AK_REWARD_CARD and int(a.idx1)==group:
                card = groups[group][int(a.idx2)]; prior = G.card_score(card,p,gc)
                if prior is not None: add(i,_add(gc,card),'take:'+G._cid(card),prior-1)
            elif k == A.AK_REWARD_SKIP and can_skip: add(i,_clone(gc),'skip',skip=True)
            elif k == A.AK_REWARD_SINGING_BOWL and int(a.idx1)==group:
                g = _clone(gc); C.F.set_max_hp(g,int(g.max_hp)+2); g.cur_hp = min(g.max_hp,g.cur_hp+2)
                add(i,g,'bowl',prior=1,skip=True)
    elif screen == 'CARD_SELECT':
        if int(gc.selection_count)!=1 or int(gc.selection_type) not in (3,4) or kinds[chosen]!=A.AK_CARD_SELECT: return []
        upgrade = int(gc.selection_type)==3
        for i,a in enumerate(actions):
            if kinds[i]!=A.AK_CARD_SELECT: continue
            j = int(a.idx1); card = gc.selection_cards[j]
            # selection_deck_indices is authoritative, including duplicate cards.
            idx = int(gc.selection_deck_indices[j])
            prior = (G.upgrade_score if upgrade else G.removal_score)(card,p)
            if prior is None: continue
            g = _up(gc,idx) if upgrade else _remove(gc,idx)
            add(i,g,('up:' if upgrade else 'remove:')+G._cid(card),prior)
    elif screen == 'REST_ROOM':
        options = {int(a.idx1):i for i,a in enumerate(actions) if kinds[i]==A.AK_REST}
        if chosen not in (options.get(0),options.get(1)): return []
        if int(gc.act)==3 and not gc.red_key: return []
        if 0 in options:
            g = _clone(gc)
            heal = int(int(g.max_hp)*.3)+(15 if 'REGAL_PILLOW' in p.relics else 0)
            if 'MARK_OF_THE_BLOOM' in p.relics: heal=0
            g.cur_hp=min(g.max_hp,g.cur_hp+heal)
            add(options[0],g,'rest',hp_value=8*(g.cur_hp-gc.cur_hp)/max(1,g.max_hp))
        if 1 in options:
            for j,card in enumerate(gc.deck):
                prior=G.upgrade_score(card,p)
                if prior is not None: add(options[1],_up(gc,j),'smith:'+G._cid(card),prior,target=j)
    elif screen == 'SHOP_ROOM':
        eligible = {A.AK_SHOP_CARD,A.AK_SHOP_RELIC,A.AK_SHOP_REMOVE,A.AK_SHOP_LEAVE,A.AK_SHOP_POTION}
        if kinds[chosen] not in eligible: return []
        cards,relics = gc.get_shop_cards(),gc.get_shop_relics()
        bottles = set(map(int,gc.bottle_indices))
        for i,a in enumerate(actions):
            k=kinds[i]
            if k==A.AK_SHOP_LEAVE: add(i,_clone(gc),'leave',skip=True)
            elif k==A.AK_SHOP_CARD:
                card,price=cards[int(a.idx1)]; prior=G.card_score(card,p,gc)
                if prior is not None and 0<=price<=gc.gold: add(i,_add(gc,card,price),'buy:'+G._cid(card),prior-1,price)
            elif k==A.AK_SHOP_RELIC:
                rid,price=relics[int(a.idx1)]; name=_name(rid)
                if name not in RELIC_PORTS or not 0<=price<=gc.gold: continue
                g=_clone(gc); g.obtain_relic(rid); g.gold=max(0,g.gold-price)
                prior=G.relic_score(name,p)
                add(i,g,'relic:'+name,prior if prior is not None else 4,price)
            elif k==A.AK_SHOP_POTION and 'THE_COURIER' not in p.relics:
                pid,price=gc.get_shop_potions()[int(a.idx1)]
                if int(pid) not in _potion_ids() or not 0<=price<=gc.gold: continue
                # Shop::buyPotion: obtain + loseGold; random restock only with Courier.
                g=_clone(gc); a.execute(g)
                add(i,g,'potion:'+_potion_ids()[int(pid)],prior=3,price=price)
            elif k==A.AK_SHOP_REMOVE and 0<=gc.shop_remove_cost<=gc.gold:
                for j,card in enumerate(gc.deck):
                    if j in bottles: continue
                    prior=G.removal_score(card,p)
                    if prior is not None: add(i,_remove(gc,j,int(gc.shop_remove_cost)),'purge:'+G._cid(card),prior,int(gc.shop_remove_cost),target=j)
    candidates=list(seen.values())
    return candidates if chosen in seen else []


def threat_panel(gc):
    """Public pools only. Never gc.encounter, encounter queues or next act boss.

    Act and canonical floor travel together: summons infer act from floor.
    Shield/Spear and Heart are independent probes, not a healed sequential run.
    """
    act=min(4,int(gc.act)); panel=[]
    if act<=3:
        panel += [(n,act,'ELITE',1.) for n in ELITES[act]]
        panel += [(_name(gc.boss),act,'BOSS',2.5)]
    if act==1: panel += [('THREE_CULTIST',2,'MONSTER',.4),('SNAKE_PLANT',2,'MONSTER',.4)]
    if act==2: panel += [('REPTOMANCER',3,'ELITE',.5),('SPIRE_GROWTH',3,'MONSTER',.4)]
    panel += [('SHIELD_AND_SPEAR',4,'ELITE',.4 if act<3 else 1.),
              ('THE_HEART',4,'BOSS',.3 if act==1 else .8 if act==2 else 2.)]
    return panel


def _public_key(gc):
    # Full combat-relevant public state including counters, misc and bottles.
    return (tuple((G._cid(c),int(c.upgrade_count),int(c.misc)) for c in gc.deck),
            tuple((_name(r.id),int(r.data)) for r in gc.relics),tuple(map(int,gc.potions)),
            tuple(map(int,gc.bottle_indices)),int(gc.max_hp),int(gc.gold),int(gc.ascension))


def _fight_value(r):
    if r['win']: return 1.+max(0,r['hp'])/max(1,r['max_hp'])
    # Surviving summoned minions can change enemy totals. Clip the proxy.
    return max(0.,min(.95,1.-r['enemy_hp_end']/max(1,r['enemy_hp_start'])))


def _evaluate(gc,panel,state,hp,started):
    import p300_common as C
    values=[]; wins=[]; losses=[]; individual_losses=[]
    public_key=_public_key(gc)
    for seed in SEEDS:
        sv=sw=sl=tw=0.
        for name,act,room,weight in panel:
            key=(public_key,name,act,room,seed,int(hp),SIMULATIONS)
            if key in state['memo']:
                r=state['memo'][key]; _stat(state,'cache_hits')
            else:
                elapsed=time.process_time()-started
                limit=ACT_CPU_LIMITS[min(4,max(1,int(state['live_act'])))-1]
                # Earn compute from CPU already spent outside these two hooks.
                # Imports, external idling and wall-clock time earn no credits.
                earned=.38*max(0.,started-state['origin_cpu']-state['cpu'])
                limit=min(limit,earned)
                # Reserve 2x largest completed call; a native call cannot be preempted.
                # Deterministic budget: fight count only (CPU-time admission made play depend on machine load).
                if state['stats']['fights']>=MAX_FIGHTS:
                    _stat(state,'budget_abstain'); return None
                g=_clone(gc); g.act=act; g.floor_num=(8,25,42,54)[act-1]
                g.cur_room=getattr(C.sts.Room,room)
                t=time.process_time()
                r=C.F.simulate(g,int(getattr(C.E,name)),SIMULATIONS,3.,seed,int(hp))
                spent=time.process_time()-t
                state['max_fight_cpu']=max(state['max_fight_cpu'],spent)
                state['simulation_cpu']+=spent
                old_cost=state['fight_cost'].get(name,spent)
                state['fight_cost'][name]=.5*old_cost+.5*spent
                _stat(state,'fights'); _stat(state,'encounter:'+name)
                if r.get('error') or int(r.get('outcome',0)) not in (1,2):
                    # Escape/unfinished/error are neither a win nor a death.
                    _stat(state,'simulation_errors')
                    state.setdefault('simulation_diagnostics',[]).append(dict(
                        encounter=name,seed=seed,hp=int(hp),result=dict(r)))
                    return None
                state['memo'][key]=r
            sv+=weight*_fight_value(r); sw+=weight*bool(r['win'])
            loss=max(0,int(hp)-max(0,r['hp']))
            sl+=weight*loss; tw+=weight; individual_losses.append(loss)
        values.append(sv/tw); wins.append(sw/tw); losses.append(sl/tw)
    return dict(values=values,value=sum(values)/len(values),win=sum(wins)/len(wins),
                loss=sum(losses)/len(losses),worst_loss=max(individual_losses))


def _shortlist(candidates,chosen):
    ranked=sorted(candidates,key=lambda c:(-c.score,c.index!=chosen,c.index))
    top=ranked[0]
    required=[top]+[c for c in ranked if c.skip]
    # Keep the parent's choice as a control if its public projection is supported.
    required += [c for c in ranked if c.index==chosen]
    required += [c for c in ranked if top.score-c.score<=2.5]
    result=[]
    for c in required:
        if c.index not in {v.index for v in result}: result.append(c)
        if len(result)==4: break
    # A single clear port winner still needs an alternative for arbitration.
    if len(result)==1 and len(ranked)>1: result.append(ranked[1])
    return result


def _panel_affordable(pool,panel,state,screen,started):
    estimate=0.; missing=set()
    for c in pool:
        public_key=_public_key(c.game)
        hp=int(c.game.cur_hp if screen=='REST_ROOM' else c.game.max_hp)
        for seed in SEEDS:
            for name,act,room,weight in panel:
                key=(public_key,name,act,room,seed,hp,SIMULATIONS)
                if key not in state['memo'] and key not in missing:
                    missing.add(key); estimate+=state['fight_cost'].get(name,.003)
    elapsed=time.process_time()-started
    earned=.38*max(0.,started-state['origin_cpu']-state['cpu'])
    limit=min(ACT_CPU_LIMITS[min(4,max(1,state['live_act']))-1],earned)
    return state['stats']['fights']+len(missing)<=MAX_FIGHTS


def _choose(x,gc,actions,kinds,chosen,parent,state,started):
    screen=_name(gc.screen_state)
    # Recall protection has priority over simulated combat value.
    if screen=='REST_ROOM' and int(gc.act)==3 and not gc.red_key:
        for i,a in enumerate(actions):
            if kinds[i]==x.A.AK_REST and int(a.idx1)==2:
                _stat(state,'recall_protected'); return i if i!=chosen else None
        return None
    pending=state.pop('pending',None)
    if (pending and screen=='CARD_SELECT' and int(gc.selection_type)==pending['type'] and
            int(gc.selection_count)==1 and _public_key(gc)==pending['key']):
        for i,a in enumerate(actions):
            if kinds[i]==x.A.AK_CARD_SELECT and int(gc.selection_deck_indices[int(a.idx1)])==pending['target']:
                _stat(state,'planned_selection'); return i if i!=chosen else None
    candidates=_candidates(x,gc,actions,kinds,chosen)
    if len(candidates)<2: return None
    pool=_shortlist(candidates,chosen); _stat(state,'decisions:'+screen)
    anchor=max(pool,key=lambda c:(c.score,c.index==chosen))
    old=next(c for c in pool if c.index==chosen)
    # Uncertain port differences preserve the incoming v1 decision.
    prior=anchor if anchor.score>=old.score+.8 else old
    panel=threat_panel(gc)
    if screen=='REST_ROOM':
        # Campfire HP choice is about the immediate known boss if adjacent.
        if int(gc.cur_map_node_y)==14 or int(gc.act)==4:
            panel=[(_name(gc.boss),int(gc.act),'BOSS',1.)] if int(gc.act)<=3 else [('SHIELD_AND_SPEAR',4,'ELITE',1.),('THE_HEART',4,'BOSS',1.)]
    results={}
    affordable=_panel_affordable(pool,panel,state,screen,started)
    if not affordable: _stat(state,'panel_admission_skips')
    for c in pool if affordable else []:
        hp=int(c.game.cur_hp if screen=='REST_ROOM' else c.game.max_hp)
        r=_evaluate(c.game,panel,state,hp,started)
        if r is None: break
        results[c.index]=r
    best=prior; reason='ports'
    # Never compare candidates with unequal/incomplete panels.
    if len(results)==len(pool):
        _stat(state,'panels_complete')
        baseline=results[prior.index]
        for c in sorted(pool,key=lambda q:-(q.score+10*results[q.index]['value'])):
            if c.index==prior.index: continue
            diffs=[a-b for a,b in zip(results[c.index]['values'],baseline['values'])]
            mean=sum(diffs)/len(diffs)
            se=sqrt(sum((d-mean)**2 for d in diffs)/(len(diffs)*(len(diffs)-1)))
            # 4 fixed seeds: evidence gate, NOT a statistical confidence claim.
            if (mean>max(.10,1.5*se) and sum(d>0 for d in diffs)>=3 and
                    c.score+10*results[c.index]['value']>prior.score+10*baseline['value']+.6):
                best=c; reason='simulation'; _stat(state,'simulation_arbitrations'); break
    else: _stat(state,'panels_incomplete')
    # A smith/purge simulation must commit the SAME card at its follow-up screen.
    if screen=='REST_ROOM' and old.label=='rest' and best.label.startswith('smith:'):
        if best.index not in results or len(results)!=len(pool) or results[best.index]['win']<1. or results[best.index]['worst_loss']>best.game.cur_hp*.55:
            best=old; reason='rest_safety'
    if best.target is not None:
        state['pending']=dict(key=_public_key(gc),target=best.target,type=3 if best.label.startswith('smith:') else 4)
    _stat(state,'selected:'+best.label.split(':')[0])
    if best.index!=chosen: _stat(state,'overrides:'+screen)
    state['decisions'].append(dict(floor=int(gc.floor_num),screen=screen,chosen=chosen,best=best.index,
                                  reason=reason,pool=[dict(index=c.index,label=c.label,score=round(c.score,3),
                                  **c.detail,simulation=results.get(c.index)) for c in pool]))
    return best.index if best.index!=chosen else None


def guide_choice2(x,gc,actions,descriptors,chosen,parent,cache) -> int | None:
    """Ports -> 2-4 candidates including safe skip -> fixed-seed arbitration.

    Incoming chosen may already include v1, or use this hook in place of v1:
    the v1 override is evaluated first. Unsupported screens defer to v1.
    """
    if not actions or len(actions)!=len(descriptors) or not 0<=chosen<len(actions): return None
    if _name(gc.screen_state) not in {'REWARDS','CARD_SELECT','REST_ROOM','SHOP_ROOM'}: return None
    state=_state(cache); state['live_act']=int(gc.act)
    def run():
        started=time.process_time()
        v1=G.guide_choice(x,_public_view(gc),actions,descriptors,chosen,parent)
        anchor=chosen if v1 is None else v1
        kinds=[x.R.kind(d) for d in descriptors]
        picked=_choose(x,gc,actions,kinds,anchor,parent,state,started)
        final=anchor if picked is None else picked
        return final if final!=chosen else None
    return _audit(x,gc,state,run)


def key_routes(gc,actions,indices,y):
    """Preserve one path satisfying BOTH green and red, using visible edges.

    Visible Wing Boots charges include current and future jumps on the same path.
    A forced key-preserving action wins even when all choices are elites.
    """
    if int(gc.act)!=3: return indices
    tx,ty=map(int,gc.burning_elite[:2])
    need_green=not gc.green_key and ty>=y
    need_red=not gc.red_key
    boots=max(0,next((int(r.data) for r in gc.relics if _name(r.id)=='WING_BOOTS'),0))
    @lru_cache(None)
    def walk(cx,cy,green,red,charges):
        green=green or (cx,cy)==(tx,ty)
        red=red or _name(gc.map_node_room(cx,cy))=='REST'
        if green and red: return True
        if cy>=14: return False
        children=list(map(int,gc.map_node_children(cx,cy)))
        if any(walk(ch,cy+1,green,red,charges) for ch in children): return True
        if charges and children:
            return any(walk(ch,cy+1,green,red,charges-1) for ch in range(7)
                       if ch not in children and _name(gc.map_node_room(ch,cy+1)) not in {'NONE','INVALID'})
        return False
    connected=list(map(int,gc.map_node_children(int(gc.cur_map_node_x),y-1))) if y>0 else []
    def supports(i,green,red):
        cx=int(actions[i].idx1)
        spent=int(bool(boots and y>0 and cx not in connected))
        return walk(cx,y,green,red,boots-spent)
    allowed=[i for i in indices if supports(i,not need_green,not need_red)]
    if allowed: return allowed
    # Existing state may already have lost a key; preserve reachable green.
    if need_green:
        allowed=[i for i in indices if supports(i,False,True)]
        if allowed: return allowed
    return indices


def guide_route2(x,gc,actions,descriptors,chosen,parent=None,cache=None) -> int | None:
    """Empirical elite-pool survival at current HP, plus hard key constraints.

    No low-probability rerolls; regular elites use one complete 3 x 4 panel.
    Burning elites require an extra HP reserve: the hidden buff is not read.
    """
    if (_name(gc.screen_state)!='MAP_SCREEN' or int(gc.act)>3 or not actions or
            len(actions)!=len(descriptors) or not 0<=chosen<len(actions)): return None
    state=_state(cache); state['live_act']=int(gc.act)
    def run():
        started=time.process_time(); y=int(gc.cur_map_node_y)+1
        if y>=15: return None
        indices=[i for i,d in enumerate(descriptors) if x.R.kind(d)==x.A.AK_MAP]
        if chosen not in indices or len(indices)<2: return None
        allowed=key_routes(gc,actions,indices,y)
        if chosen not in allowed:
            _stat(state,'key_route_protected'); return allowed[0]
        rooms={i:_name(gc.map_node_room(int(actions[i].idx1),y)) for i in allowed}
        if 'ELITE' not in rooms.values(): return None
        panel=[(n,int(gc.act),'ELITE',1.) for n in ELITES[int(gc.act)]]
        r=_evaluate(gc,panel,state,int(gc.cur_hp),started)
        if r is None: return None
        _stat(state,'route_panels')
        tx,ty=map(int,gc.burning_elite[:2])
        # 12 samples are empirical probes, never calibrated elite win odds.
        def ready(i):
            flame=(int(actions[i].idx1),y)==(tx,ty)
            return r['win']>=1. and r['worst_loss']<=gc.cur_hp*.45-(15 if flame else 0) and gc.cur_hp-r['worst_loss']>=18+(12 if flame else 0)
        good=[i for i in allowed if rooms[i]=='ELITE' and ready(i)]
        best=chosen
        if good and rooms[chosen] in {'MONSTER','EVENT','ELITE'} and chosen not in good: best=good[0]
        elif rooms[chosen]=='ELITE' and not ready(chosen):
            safe=[i for i in allowed if rooms[i] in {'REST','SHOP','EVENT','TREASURE','MONSTER'}]
            if safe:
                weights={'REST':5 if gc.cur_hp<gc.max_hp*.7 else 2,'SHOP':4 if gc.gold>=150 else 0,'TREASURE':3,'EVENT':2,'MONSTER':1}
                best=max(safe,key=lambda i:weights[rooms[i]])
        state['decisions'].append(dict(floor=int(gc.floor_num),screen='MAP_SCREEN',chosen=chosen,best=best,
                                      reason='elite_panel',simulation=r,allowed=allowed))
        if best!=chosen: _stat(state,'overrides:MAP_SCREEN')
        return best if best!=chosen else None
    return _audit(x,gc,state,run)
