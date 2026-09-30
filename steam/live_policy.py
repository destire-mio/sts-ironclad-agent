"""Frozen parent/P300 policy on an original-authoritative native run context."""
from __future__ import annotations
import ast
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sim_patch.parity.core import sha256, differences
from sim_patch.parity.adapter import rng_bits


def norm(value):
    return ''.join(c.lower() for c in str(value) if c.isalnum())


def functions_from(path, names, namespace):
    """Load unchanged pure policy functions without the experiment CLI/import side effects."""
    tree = ast.parse(path.read_text(), filename=str(path))
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in selected} != set(names):
        raise ValueError('frozen policy functions missing')
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


class LivePolicy:
    def __init__(self, search, seed):
        self.search, self.sts, self.native = search, search.sts, search.native
        runtime = search.runtime
        manifest = json.loads((runtime / 'live-manifest.json').read_text())
        for relative, expected in manifest['runtime_files'].items():
            if sha256(runtime / relative) != expected:
                raise ValueError('frozen parent input changed: ' + relative)
        for entry in manifest['p300_inputs'].values():
            if sha256(runtime / entry['path']) != entry['sha256']:
                raise ValueError('frozen value table changed: ' + entry['path'])
        sys.path[:0] = [str(runtime / 'source'), str(runtime), str(runtime / 'p300/agent')]
        self.A = importlib.import_module('armG_train')
        self.R = importlib.import_module('heart_runtime')
        self.H = importlib.import_module('heart_train')
        self.F = importlib.import_module('fightsim')
        self.H.torch.set_num_threads(1)
        self.parent = self.H.load_scorer(self.H.torch.load(runtime / 'model.pt', weights_only=True, map_location='cpu'))
        self.x = SimpleNamespace(A=self.A, R=self.R)
        teacher = functions_from(runtime / 'p300/agent/p300_teacher.py', ['deck_key', 'deck_delta'], {})
        self.P = functions_from(runtime / 'p300/agent/p300_play.py',
            ['sv_choice', 'teacher_indices', 'pre_boss_rest'], {'C': SimpleNamespace(sts=self.sts, F=self.F), 'T': teacher})
        self.stage_values = importlib.import_module('p300_stage_values')
        self.stage_values.tables()  # Validate collections before opening the original.
        self.gc = self.sts.GameContext(self.sts.CharacterClass.IRONCLAD, seed, 20)
        catalog = self.native.live_catalog()
        self.events = {norm(name): i for i, name in enumerate(catalog['events'])}
        self.events['neowevent'] = self.events['neow']
        self.encounters = {norm(name): self.sts.MonsterEncounter(i) for i, name in enumerate(catalog['encounters'])}
        self.card_reward_group = None
        self.last_floor = -1
        self.shop_floor = None
        self.shop_identities = {}
        self.shop_original = {}
        self.shop_purchase = None

    def card(self, raw):
        snap = self.search.comparator.bridge.card_snapshot(raw)
        c = self.sts.Card(self.sts.CardId(snap['id']))
        for _ in range(raw.get('upgrades', 0)):
            c.upgrade()
        if c.id.name == 'RITUAL_DAGGER':
            c.misc = raw.get('misc', 15)
        return c

    def relic(self, name):
        return self.sts.RelicId(self.sts.relic_id_from_name(name))

    def potion(self, name):
        return self.sts.potion_id_from_name('EMPTY_POTION_SLOT' if name == 'Potion Slot' else name)

    def relic_counter(self, raw):
        # Java's default UI sentinel is -1; the frozen policy was trained on
        # native zero for relics without a counter. Preserve stateful sentinels.
        name=self.relic(raw['id']).name
        if raw['counter']==-1 and name not in {'ANCIENT_TEA_SET','LIZARD_TAIL','MAW_BANK'}:
            return 0
        return raw['counter']

    def encounter(self, name):
        key = norm(name).replace('2', 'two').replace('3', 'three').replace('4', 'four')
        aliases = {'sphericguardianandshapes': 'sphereandtwoshapes', 'sentryandsphericguardian': 'sentryandsphere',
                   'thecollector': 'collector', 'thechamp': 'champ', 'bronzeautomaton': 'automaton',
                   'heart': 'theheart', 'spiregrowth': 'spiregrowth', 'shieldandspear': 'shieldandspear',
                   'threecultists':'threecultist'}
        return self.encounters[aliases.get(key, key)]

    def rewards(self, rows):
        result = dict(gold=[], cards=[], relics=[], potions=[], emerald=False, sapphire=False)
        for row in rows:
            if row.get('done'):
                continue
            kind = row['type']
            if kind in ('GOLD', 'STOLEN_GOLD'): result['gold'].append(row['gold'])
            elif kind == 'CARD': result['cards'].append([self.card(c) for c in row['cards']])
            elif kind == 'RELIC': result['relics'].append(self.relic(row.get('relic', row.get('id'))))
            elif kind == 'POTION': result['potions'].append(self.potion(row.get('potion', row.get('id'))))
            elif kind == 'EMERALD_KEY': result['emerald'] = True
            elif kind == 'SAPPHIRE_KEY': result['sapphire'] = True
            else: raise ValueError('unsupported original reward: ' + kind)
        return result

    def sync(self, view):
        g, r, S = view['game'], view['live_run'], self.sts
        self.gc.outcome=S.GameOutcome.UNDECIDED
        screen = g['screen_type']
        screens = {'EVENT':'EVENT_SCREEN', 'MAP':'MAP_SCREEN', 'REST':'REST_ROOM', 'SHOP_SCREEN':'SHOP_ROOM',
                   'COMBAT_REWARD':'REWARDS', 'CARD_REWARD':'REWARDS', 'BOSS_REWARD':'BOSS_RELIC_REWARDS',
                   'CHEST':'TREASURE_ROOM', 'GRID':'CARD_SELECT', 'NONE':'BATTLE'}
        if screen not in screens: raise ValueError('unhandled original policy screen: ' + screen)
        rooms = {'NeowRoom':'INVALID', 'MonsterRoom':'MONSTER', 'MonsterRoomElite':'ELITE',
                 'MonsterRoomBoss':'BOSS', 'RestRoom':'REST', 'ShopRoom':'SHOP', 'EventRoom':'EVENT',
                 'TreasureRoom':'TREASURE', 'TreasureRoomBoss':'BOSS_TREASURE', 'TrueVictoryRoom':'BOSS'}
        rng = {k:rng_bits(v) for k,v in view['rng'].items() if k != 'mapRng'}
        for name, target in [('NeowEvent.rng','neowRng'), ('MathUtils.random','mathUtilRng')]:
            raw = g['full_rng_state']['streams'][name]
            if raw['initialized']:
                rng[target] = {**rng_bits({**raw, 'counter':raw.get('counter', 0)})}
        deck = r['deck']
        first_map=screen=='MAP' and not g['screen_state'].get('first_node_chosen',True)
        # At an act's first map the Java current-room object still belongs to
        # the preceding act. Native preserves curRoom until the first node too.
        room=self.gc.cur_room if first_map or r['room']=='EmptyRoom' else getattr(S.Room,rooms[r['room']])
        changes = dict(screen=getattr(S.ScreenState,screens[screen]), room=room,
            hp=g['current_hp'], max_hp=g['max_hp'], gold=g['gold'], act=g['act'], floor=g['floor'],
            x=(-1 if first_map or r['y']<0 else r['x']), y=(-1 if first_map else r['y']), red=view['ruby'], green=view['emerald'], blue=view['sapphire'],
            potion_capacity=len(g['potions']), potions=[self.potion(p['id']) for p in g['potions']],
            deck=[dict(card=self.card(c),bottled=c['bottled']) for c in deck],
            relics=[(self.relic(a['id']),self.relic_counter(a)) for a in g['relics']], rng=rng,
            boss=self.encounter(r['boss']), shop_remove_count=max(0,(r['purge_cost']-75)//25),
            card_rarity_factor=r['card_rarity_factor'], potion_chance=r['potion_chance'],
            monster_chance=r['event_chances'][1],shop_chance=r['event_chances'][2],treasure_chance=r['event_chances'][3],
            speedrun=view['play_time_seconds']<800)
        # Java removes a boss from bossList on entering its room. Before the
        # first Act-3 fight there are three entries, during it two, and during
        # the second fight one. Do not retain a secondBoss that is now current:
        # native afterBattle would otherwise schedule a third boss fight.
        remaining=r['bossList']
        changes['second_boss']=(self.encounter(remaining[1 if len(remaining)==3 else 0])
            if g['act']==3 and len(remaining)>=2 else S.MonsterEncounter.INVALID)
        room_symbols = {'M':'MONSTER','E':'ELITE','R':'REST','$':'SHOP','?':'EVENT','T':'TREASURE','B':'BOSS'}
        changes['map'] = [dict(x=n['x'],y=n['y'],room=getattr(S.Room,room_symbols[n['symbol']]),
                              edges=[e['x'] for e in n.get('children',[])]) for n in g['map'] if n['y']<15]
        # The original omits its boss icon. Native Act 4 uses an ordinary node
        # at (3,3), unlike the special row 15 in Acts 1-3.
        if g['act']==4 and not any(n['x']==3 and n['y']==3 for n in changes['map']):
            changes['map'].append(dict(x=3,y=3,room=S.Room.BOSS,edges=[]))
        flame = view.get('burning_elite', {})
        changes['burning'] = [flame.get('x',-1),flame.get('y',-1),self.gc.burning_elite[2]]
        for pool in ('common','uncommon','rare','shop','boss'):
            changes[pool+'_pool'] = [self.relic(v) for v in r['pools'][pool]]
        # Java removes the current encounter on LEAVING the room. Native
        # advances its offset on ENTERING, so its remaining list excludes it.
        changes['monster_list'] = [self.encounter(v) for v in r['monsterList'][int(r['room'] in ('MonsterRoom','MonsterRoomBoss')):]]
        changes['elite_list'] = [self.encounter(v) for v in r['eliteMonsterList'][int(r['room']=='MonsterRoomElite'):]]
        for old,new in [('eventList','event_list'),('shrineList','shrine_list'),('specialOneTimeEventList','one_time_events')]:
            changes[new] = [self.events[norm(v)] for v in r[old]]
        info = {}
        if screen == 'EVENT':
            event_id = g['screen_state']['event_id']
            changes['event'] = self.events[norm(event_id)]
            if event_id == 'Neow Event':
                bonuses = 'THREE_CARDS ONE_RANDOM_RARE_CARD REMOVE_CARD UPGRADE_CARD TRANSFORM_CARD RANDOM_COLORLESS THREE_SMALL_POTIONS RANDOM_COMMON_RELIC TEN_PERCENT_HP_BONUS THREE_ENEMY_KILL HUNDRED_GOLD RANDOM_COLORLESS_2 REMOVE_TWO ONE_RARE_RELIC THREE_RARE_CARDS TWO_FIFTY_GOLD TRANSFORM_TWO_CARDS TWENTY_PERCENT_HP_BONUS BOSS_RELIC INVALID'.split()
                drawbacks = 'INVALID NONE TEN_PERCENT_HP_LOSS NO_GOLD CURSE PERCENT_DAMAGE LOSE_STARTER_RELIC'.split()
                changes['neow'] = [(bonuses.index(n['bonus']),drawbacks.index('LOSE_STARTER_RELIC' if n['bonus']=='BOSS_RELIC' else n['drawback'])) for n in r['neow']]
            fields = r['event_fields']
            for java,key in [('goldLoss','gold_loss'),('adjustmentUpgradesOne','upgrade_one'),('cleanUpRemovesCards','cleanup_remove')]:
                if java in fields: info[key]=fields[java]
            indices={c['uuid']:i for i,c in enumerate(deck)}
            if event_id=='WeMeetAgain':
                info['gold']=fields['goldAmount']
                info['card_index']=indices[fields['cardOption']['uuid']] if 'cardOption' in fields else -1
                if 'potionOption' in fields:info['potion_index']=fields['potionOption']['slot']
            if event_id=='Falling':
                for java,key in [('skillCard','fall_skill'),('powerCard','fall_power'),('attackCard','fall_attack')]:
                    info[key]=indices[fields[java]['uuid']] if java in fields else -1
            if norm(event_id)=='nloth':
                ids=[a['id'] for a in g['relics']]
                info['relic0']=ids.index(fields['choice1']);info['relic1']=ids.index(fields['choice2'])
            if event_id=='Scrap Ooze':info['event_data']=(fields['relicObtainChance']-25)//10
            if event_id=='Dead Adventurer':info['phase']=fields['numRewards']
            if event_id=='Knowing Skull':
                info.update(hp0=fields['potionCost'],hp1=fields['goldCost'],hp2=fields['cardCost'])
        if screen in ('COMBAT_REWARD','CARD_REWARD'):
            rows = r['rewards']
            if screen == 'CARD_REWARD' and not rows:
                rows = [dict(type='CARD',cards=g['screen_state']['cards'])]
            changes['rewards']=self.rewards(rows)
        if screen == 'BOSS_REWARD':
            changes['boss_relics']=[self.relic(v['id']) for v in g['screen_state']['relics']]
        if screen == 'GRID':
            uuids={c['uuid']:i for i,c in enumerate(deck)}
            f=r['grid_fields']
            selected={c['uuid'] for c in f['selectedCards']}
            self.grid_candidates=[c for c in r['grid_cards'] if c['uuid'] not in selected]
            changes['selection']=[(self.card(c),uuids.get(c['uuid'],-1)) for c in self.grid_candidates]
            changes['selected']=[(self.card(c),uuids.get(c['uuid'],-1)) for c in f['selectedCards']]
            # The native continuation specifies transform/obtain/bottle semantics;
            # original flags override the generic upgrade and removal operations.
            info['select_count']=f['numCards']
            if f.get('forUpgrade'):info['select_type']=3
            elif f.get('forPurge'):info['select_type']=4
            elif f.get('forTransform'):info['select_type']=2 if int(self.gc.selection_type)==2 else 1
        if screen == 'SHOP_SCREEN':
            s=g['screen_state']; stock=dict(cards=[S.Card(S.CardId.INVALID) for _ in range(7)],
                relics=[S.RelicId.INVALID]*3,potions=[self.potion('INVALID')]*3,prices=[-1]*13,remove=s.get('purge_cost',r['purge_cost']))
            if self.shop_floor!=g['floor']:
                self.shop_floor=g['floor'];self.shop_identities={};self.shop_purchase=None
            for group,offset,convert in [('cards',0,self.card),('relics',7,lambda c:self.relic(c['id'])),('potions',10,lambda c:self.potion(c['id']))]:
                identity=lambda c:c['uuid'] if group=='cards' else c['id']
                if group in r.get('shop_slots',{}):
                    slots=r['shop_slots'][group]
                    if [c['id'] for c in s[group]]!=[c['id'] for c in slots]:
                        raise ValueError('independent shop stock export differs')
                    self.shop_original[group]={}
                    for c,slot in zip(s[group],slots):
                        i=slot['slot'];self.shop_original[group][i]=c
                        stock[group][i]=convert(c);stock['prices'][offset+i]=c['price']
                    continue
                if group not in self.shop_identities:
                    if len({identity(c) for c in s[group]})!=len(s[group]):
                        raise ValueError('duplicate stock requires original slot export')
                    self.shop_identities[group]={identity(c):i for i,c in enumerate(s[group])}
                mapping=self.shop_identities[group];self.shop_original[group]={}
                for c in s[group]:
                    key=identity(c)
                    if key not in mapping:
                        if not self.shop_purchase or self.shop_purchase[0]!=group:
                            raise ValueError('unattributed original shop restock')
                        mapping[key]=self.shop_purchase[1]
                    i=mapping[key];self.shop_original[group][i]=c
                    stock[group][i]=convert(c);stock['prices'][offset+i]=c['price']
            if not s.get('purge_available',True):stock['remove']=-1
            changes['shop']=stock
        if g.get('combat_state'):
            encounter=self.search.comparator.bridge.encounter_id(g['combat_state']['monsters'])
            if encounter:info['encounter']=S.MonsterEncounter(encounter)
        changes['info']=info
        self.native.sync_run(self.gc, changes)
        self.last_floor=g['floor']

    def choose(self, view):
        self.sync(view)
        gc,A=self.gc,self.A
        actions=list(self.sts.get_legal_game_actions(gc))
        _,descriptors,_=A.build_choices(gc)
        if not actions:raise ValueError('no native outside actions')
        # Validate every action's original transport before scoring. A missing
        # mapping is an integration error, never a silently deleted candidate.
        commands=[self.commands(a,view) for a in actions]
        observation=A.obs_vec(gc)
        with self.H.torch.no_grad():
            parent=self.parent.choose(gc,observation,actions,descriptors)
        chosen=parent; rule='parent'
        rest=self.P.pre_boss_rest(self.x,gc,actions,descriptors)
        if rest is not None:chosen=rest;rule='pre_boss_rest'
        indices=self.P.teacher_indices(self.x,gc,actions,descriptors,chosen)
        if len(actions)>1 and indices:
            best=self.P.sv_choice(gc,actions,indices,0.01)
            if best is not None:chosen=best;rule='stage_values'
        if gc.screen_state==self.sts.ScreenState.SHOP_ROOM and not actions[chosen].is_potion_action:
            group={'CARD':'cards','RELIC':'relics','POTION':'potions'}.get(actions[chosen].rewards_action_type.name)
            if group:self.shop_purchase=(group,int(actions[chosen].idx1))
        return actions[chosen],commands[chosen],dict(parent=parent,chosen=chosen,rule=rule,
            actions=[int(a.bits) for a in actions],commands=commands,observation=observation,descriptors=descriptors)

    def commands(self, action, view):
        g=view['game']; screen=g['screen_type']; s=g['screen_state'];i,j=int(action.idx1),int(action.idx2)
        if action.is_potion_action:return [f'potion {"discard" if action.is_potion_discard else "use"} {i}']
        if screen=='MAP':
            if s.get('boss_available'):return ['choose 0']
            return ['choose '+str(next(k for k,n in enumerate(s['next_nodes']) if n['x']==i))]
        if screen=='EVENT':
            event=g['screen_state']['event_id']
            if event=='Cursed Tome' and i>=2:i=0 if i<6 else 1
            elif event=='Designer':i=0 if i<2 else 1 if i<4 else i-2
            elif event=='Golden Idol' and i>=2:i-=2
            elif event=='MindBloom' and i==3:i=2
            elif event=='Vampires':
                i={0:1,1:0,2:2 if view['live_run']['event_fields']['hasVial'] else 1}[i]
            # Native options keep their physical button index; CommunicationMod
            # numbers only enabled buttons. Disabled entries remain in options.
            option=s['options'][i]
            if option['disabled']:raise ValueError('native event action is disabled in the original')
            return ['choose '+str(option['choice_index'])]
        if screen=='REST':
            name=['rest','smith','recall','lift','toke','dig','leave'][i]
            labels=g['choice_list']
            return ['choose '+str([norm(v) for v in labels].index(name))]
        if screen=='CHEST':return ['choose 0'] if i==0 else ['proceed']
        if screen=='BOSS_REWARD':return [f'choose {i}'] if i<3 else ['skip']
        kind=action.rewards_action_type.name
        if screen=='GRID':
            if kind=='SKIP':return ['cancel']
            target=self.grid_candidates[i]['uuid']
            options=s['cards'];return ['choose '+str(next(k for k,c in enumerate(options) if c['uuid']==target))]
        if screen in ('COMBAT_REWARD','CARD_REWARD'):
            if kind=='SKIP':return ['skip'] if screen=='CARD_REWARD' else ['proceed']
            if screen=='CARD_REWARD':
                if kind!='CARD':raise ValueError('non-card reward on card screen')
                return ['bowl' if j==5 else f'choose {j}']
            types={'GOLD':('GOLD','STOLEN_GOLD'),'RELIC':('RELIC',),'POTION':('POTION',),'CARD':('CARD',),'KEY':('SAPPHIRE_KEY','EMERALD_KEY')}
            rows=s['rewards'];indices=[k for k,r in enumerate(rows) if r['reward_type'] in types[kind]]
            chosen=indices[i] if kind!='KEY' else indices[0]
            return [f'choose {chosen}']+(['bowl' if j==5 else f'choose {j}'] if kind=='CARD' else [])
        if screen=='SHOP_SCREEN':
            if kind=='SKIP':return ['leave']
            labels=g['choice_list']
            if kind=='CARD_REMOVE':return ['choose '+str(labels.index('purge'))]
            group={'CARD':'cards','RELIC':'relics','POTION':'potions'}[kind]
            raw=self.shop_original[group][i]; label=norm(raw.get('name',raw['id']))
            matches=[k for k,v in enumerate(labels) if norm(v)==label]
            ordinal=sum(1 for slot,c in self.shop_original[group].items() if slot<i and c['id']==raw['id'] and c['price']<=g['gold'])
            return ['choose '+str(matches[ordinal])]
        raise ValueError('unmapped native action: '+repr(action))

    def projection(self):
        from steam.live_state import projection
        return projection(self)

    def compare(self, view, before):
        from steam.live_state import compare
        return compare(self,view,before)
