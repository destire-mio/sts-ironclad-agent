"""Original shop purchases, child-screen decisions and native continuation replay."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import struct

from .core import differences, digest, read_json, sha256, write_json
from .treasure import project as reward_project, category_order_difference


def project(state):
    out=reward_project(state)
    if 'math_rng' in out:
        out['math_rng']={k:int(v)%(1<<64) for k,v in out['math_rng'].items()}
    if 'presentation_rng' in out:
        # Compare Java/C++ float32 values, not their differing JSON spellings.
        def bits(value):
            if isinstance(value,float):return {'float32_bits':struct.unpack('!I',struct.pack('!f',value))[0]}
            if isinstance(value,dict):return {k:bits(v) for k,v in value.items()}
            if isinstance(value,list):return [bits(v) for v in value]
            return value
        out['presentation_rng']=bits(out['presentation_rng'])
    return out


def presentation_state(view,purge=False,rewards=False,upgrade=False):
    p=view['presentation'];f=p['floaty'];d=p['dialog']
    out={'frame':p['frame'],'active':view['state']['phase']=='shop','character_words':p['character_words'],
         'said_welcome':p['shop']['ShopScreen.saidWelcome'],
         'speech_timer':float(p['shop']['ShopScreen.speechTimer']),
         'floaty':{key:float(f['FloatyEffect.'+field]) for key,field in
             [('x','x'),('y','y'),('vx','vX'),('vy','vY'),('min_v','minV'),('max_v','maxV'),
              ('threshold','threshold'),('speed_scale','speedScale')]},'dialog':None}
    if d:
        out['dialog']={'duration':float(d['AbstractGameEffect.duration']),
            'word_timer':float(d['SpeechTextEffect.wordTimer']),'text_done':d['SpeechTextEffect.textDone'],
            'words':[{'effect':w['SpeechWord.effect'],'timer':float(w['SpeechWord.timer']),
                      'characters':len(w['text'].encode('utf-16-le'))//2} for w in p['words']]}
    if purge:
        effects=p['purge_effects']
        if len(effects)>1:raise ValueError('multiple purge effects outside current shop profile')
        out.update(disable_effects=p['disable_effects'],purge_effect=None if not effects else
            {'duration':float(effects[0]['duration']),'fading':effects[0]['fading']},
            purge_particles={key:[float(v) for v in p['purge_particles'][key]] for key in ('top','regular')},
            panel_glows={key:[float(v) for v in p['panel_glows'][key]] for key in ('draw','discard_above','discard_below')},
            scene={'type':p['scene']['type'],'width':p['scene']['width'],
                **{key:[float(v) for v in p['scene'][key]] for key in ('dust','fog','torch_particles','light_flares')},
                'torches':[{**t,'timer':float(t['timer'])} for t in p['scene']['torches']]})
    if rewards:
        # Gson omits nullable object members when serializing a JsonObject.
        out['reward_tips']={**p['reward_tips'],'selected':p['reward_tips'].get('selected')}
        out['healing']={'lines':[{**v,'duration':float(v['duration']),'stagger':float(v['stagger'])} for v in p['healing']['lines']],
            'numbers':[float(v) for v in p['healing']['numbers']]}
        out.update(scale=float(p['scale']),rewards_visible=p['rewards_visible'],
            potion_displays={k:[{**v,'timer':float(v['timer'])} for v in p['potion_displays'][k]] for k in ('shop','rewards')},
            potion_particles=[{**v,'duration':float(v['duration'])} for v in p['potion_particles']])
    if upgrade:
        e=p['upgrade_effects']
        out['upgrade_effects']={
            'shines':[{**v,'duration':float(v['duration'])} for v in e['shines']],
            'briefs':[{**v,'duration':float(v['duration'])} for v in e['briefs']],
            **{k:[float(v) for v in e[k]] for k in ('hammers','sparks')}}
    return out


def presentation_input(view,frames,action_frames=None):
    upgrade=action_frames is not None and 'UPGRADE' in action_frames
    obtain=action_frames is not None and 'MIRROR' in action_frames
    rewards=action_frames is not None and 'REWARD_RETURN' in action_frames
    purge=rewards or (action_frames is not None and 'REMOVE' in action_frames)
    p=view['presentation'];out=presentation_state(view,purge,rewards,upgrade);out.pop('active')
    out.update(profile='installed-shop-card-v1',purchase_frames=frames,delta=p['delta'],
        fast_mode=p['fast_mode'],backgrounded=p['backgrounded'],
        initial_effects_settled=p['effects_settled'],touch_screen=p['touch_screen'],controller=p['controller'],
        effects=p['effects'],buy_messages=p['shop_names'][7:12])
    if action_frames is not None:
        out.update(profile='installed-shop-v6' if upgrade else ('installed-shop-v5' if obtain else ('installed-shop-v4' if rewards else ('installed-shop-v3' if purge else 'installed-shop-v2'))),action_frames=action_frames,
            welcome_message=p['shop_names'][0],idle_messages=p['idle_messages'],
            full_potion_message=p['full_potion_message'],bubble_hovered=p['bubble_hovered'],
            bubble_matches_dialog=p['bubble_matches_dialog'])
    if rewards:out['debug_mode']=p['debug_mode']
    return out


def frame_budget(spec,step):
    if 'action_frames' in spec:
        kind=step['kind'];key={'grid':'GRID','discard':'DISCARD','leave':'LEAVE'}.get(kind)
        if kind=='grid' and step.get('purge'):key='PURGE_CONFIRM'
        if kind=='grid' and step.get('mirror'):key='MIRROR'
        if kind=='grid_cancel':key='PURGE_CANCEL'
        if kind=='buy':key='BLOCKED_POTION' if step.get('blocked') else step.get('type','RELIC')
        if kind=='buy' and step.get('upgrade'):key='UPGRADE'
        if kind=='card_peek_skip':key='REWARD_PEEK'
        if kind=='reward':
            key='REWARD_RETURN' if step['type']=='SKIP' else ('REWARD_BOWL' if step.get('pick')==5 else 'REWARD_'+step['type'])
        if key is None or key not in spec['action_frames']:raise ValueError('no declared clock for shop action: '+kind)
        return spec['action_frames'][key]
    if 'presentation_frames' in spec:
        if step['kind']=='buy' and step.get('type')=='CARD':return spec['presentation_frames']
        if step['kind']=='leave':return 4
        raise ValueError('card-only presentation clock received another action')
    return None


def comparison_state(view,presentation=False,purge=False,rewards=False,upgrade=False):
    state=dict(view['state'])
    if presentation:state['presentation_rng']=presentation_state(view,purge or rewards,rewards,upgrade)
    return project(state)


def unusable_potion_domain(diff,expected,actual):
    """Keep original affordable clicks distinct from native effectful actions."""
    parts=diff['path'].split('/')
    if len(parts)<4 or parts[1]!='views' or parts[3]!='shop_actions':return False
    index=int(parts[2]);e=expected['views'][index];a=actual['views'][index]
    blocked=any(r['id']=='Sozu' for r in e['relics']) or all(p!='Potion Slot' for p in e['potions'])
    if not blocked or e['phase']!='shop' or a['phase']!='shop':return False
    if e['stock']!=a['stock'] or e['potions']!=a['potions'] or e['relics']!=a['relics'] or e['gold']!=a['gold']:return False
    return ([x for x in e['shop_actions'] if x['type']!='POTION']==a['shop_actions']
        and [x for x in e['shop_actions'] if x['type']=='POTION']==[
            {'type':'POTION','index':p['slot']} for p in e['stock']['potions'] if p['price']<=e['gold']]
        and any(x['type']=='POTION' for x in e['shop_actions'])
        and all(x['type']!='POTION' for x in a['shop_actions']))


def capture(repo, oracle, specs, directory):
    from .campaign import enter_first_battle
    from .oracle import Original
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory/'capture-plan.json', {'specs': specs, 'source_sha256': sha256(__file__),
        'case_isolation': 'fresh original JVM per case, serial port18119',
        'scope': 'declared pre-purchase stock and RNG inputs; ordinary purchase, grid, reward, discard and leave commands'})
    rows=[]
    for i,spec in enumerate(specs):
        row={'spec':spec,'steps':[],'views':[]}
        try:
            with Original(oracle,directory/f'original-{i:05d}',repo) as game:
                enter_first_battle(game)
                row['setup']=game.call('shop_continuation_fixture',spec=spec)
                checkpoint=row['setup']['checkpoint']; row['views'].append(checkpoint)
                card_slots=list(range(len(spec['stock']['cards'])))
                courier=any((r if isinstance(r,str) else r['id'])=='The Courier' for r in spec['relics'])

                command_frames=[]
                def call_command(command):
                    value=game.call('command',command=command)
                    if 'math_rng' in spec:
                        command_frames.append(game.call('shop_continuation_observe')['presentation']['frame'])
                    return value

                def advance(step):
                    if 'math_rng' in spec:
                        step['command_frames']=list(command_frames);command_frames.clear()
                    budget=frame_budget(spec,step)
                    target=row['views'][-1]['presentation']['frame']+budget if budget is not None else None
                    row['steps'].append(step)
                    value=game.call('shop_continuation_observe')
                    if target is not None:
                        step['declared_observation_frame']=target
                        value=game.call('shop_continuation_advance',frame=target)
                    row['views'].append(value)
                    return value

                if checkpoint['state']['phase']!='shop': raise ValueError('shop did not open')
                if 'unaffordable_slot' in spec:
                    if spec['unaffordable_slot'] in checkpoint['state']['legal_relic_slots']:
                        raise ValueError('expected unaffordable relic is offered as affordable')
                for purchase in spec['purchases']:
                    kind=purchase.get('type','RELIC');slot=purchase.get('slot',0)
                    if kind=='DISCARD':
                        command=f'potion discard {slot}'
                        checkpoint=advance({'kind':'discard','index':slot,'commands':[command],
                            'raw_views':[call_command(command)]})
                        continue
                    ui_slot=slot
                    if kind=='CARD':
                        ui_slot=card_slots.index(slot);item=checkpoint['state']['stock']['cards'][ui_slot]
                    elif kind in ('RELIC','POTION'):
                        item=next(r for r in checkpoint['state']['stock'][kind.lower()+'s'] if r['slot']==slot)
                    elif kind=='REMOVE':item={}
                    else:raise ValueError('unsupported purchase type: '+kind)
                    if 'id' in purchase and item.get('id')!=purchase['id']:raise ValueError('requested item differs from stock')
                    ui=checkpoint['shop_choices'].index({'type':kind,'index':ui_slot})
                    command=f'choose {ui}'
                    raw=call_command(command)
                    step={'kind':'buy','slot':slot,'commands':[command],'raw_views':[raw]}
                    if kind!='RELIC':step['type']=kind
                    if kind=='RELIC' and item.get('id') in ('Whetstone','War Paint') and 'UPGRADE' in spec.get('action_frames',{}):
                        step['upgrade']=True
                    if purchase.get('blocked'):step['blocked']=True
                    checkpoint=advance(step)
                    if kind=='CARD' and not courier:card_slots.remove(slot)
                    if checkpoint['state']['phase']=='grid':
                        if purchase.get('grid_pick')=='cancel':
                            if 'cancel' not in checkpoint['view']['available_commands']:raise ValueError('grid cancel unavailable')
                            step={'kind':'grid_cancel','commands':['cancel'],'raw_views':[call_command('cancel')]}
                        else:
                            choices=checkpoint['state']['selection']['choices']
                            pick=len(choices)-1 if purchase.get('grid_pick')=='last' else int(purchase.get('grid_pick',0))
                            if not 0<=pick<len(choices): raise ValueError('grid pick unavailable')
                            command=f'choose {pick}'; raw=call_command(command)
                            step={'kind':'grid','index':pick,'commands':[command],'raw_views':[raw]}
                            if kind=='REMOVE':step['purge']=True
                            if kind=='RELIC' and item.get('id')=='DollysMirror':step['mirror']=True
                            if raw['game']['screen_type']=='GRID' and 'confirm' in raw['available_commands']:
                                step['commands'].append('confirm'); step['raw_views'].append(call_command('confirm'))
                        checkpoint=advance(step)
                    if checkpoint['state']['phase']=='rewards':
                        for decision in purchase.get('reward_plan',[]):
                            requested=decision['type']; index=decision.get('index',0)
                            if requested=='DISCARD':
                                command=f'potion discard {index}'
                                checkpoint=advance({'kind':'discard','index':index,'commands':[command],
                                    'raw_views':[call_command(command)]})
                                continue
                            kind='CARD' if requested=='CARD_SKIP' else requested
                            candidates=checkpoint['state']['reward_groups'][kind]
                            if not 0<=index<len(candidates): raise ValueError('reward unavailable: '+str(decision))
                            ui=checkpoint['state']['reward_order'].index({'type':kind,'index':index})
                            command=f'choose {ui}'; raw=call_command(command)
                            step={'kind':'card_peek_skip' if requested=='CARD_SKIP' else 'reward',
                                'type':kind,'index':index,'commands':[command],'raw_views':[raw]}
                            if kind=='CARD':
                                if raw['game']['screen_type']!='CARD_REWARD': raise ValueError('card reward did not open')
                                if requested=='CARD_SKIP': command='skip'
                                elif decision.get('pick')=='bowl':
                                    if not raw['game']['screen_state']['bowl_available']: raise ValueError('bowl unavailable')
                                    command='choose '+str(raw['game']['choice_list'].index('bowl'));step['pick']=5
                                else:
                                    step['pick']=int(decision.get('pick',0));command=f"choose {step['pick']}"
                                step['commands'].append(command);step['raw_views'].append(call_command(command))
                            checkpoint=advance(step)
                            if checkpoint['state']['phase']!='rewards': raise ValueError('reward did not return to reward screen')
                        # Installed CommunicationMod omits the visible reward return
                        # button. The existing oracle clicks its native hitbox.
                        raw=call_command('cancel_shop_reward')
                        step={'kind':'reward','type':'SKIP','commands':['cancel_shop_reward'],'raw_views':[raw]}
                        if raw['game']['screen_type']=='SHOP_ROOM':
                            command='choose '+str(raw['game']['choice_list'].index('shop'))
                            step['commands'].append(command);step['raw_views'].append(call_command(command))
                        checkpoint=advance(step)
                    if checkpoint['state']['phase']!='shop': raise ValueError('purchase did not return to shop: '+checkpoint['state']['phase'])
                # The original closes SHOP into ShopRoom before proceeding to MAP.
                # Native exit is one atomic action; both UI transitions remain in evidence.
                raw=call_command('leave')
                screen=raw['game']['screen_type']
                # After an empty reward screen followed by a grid, the original
                # may restore that empty screen while leaving SHOP. Preserve it.
                empty_return=screen=='COMBAT_REWARD' and raw['game']['screen_state'].get('rewards')==[]
                if screen!='SHOP_ROOM' and not empty_return: raise ValueError('shop leave did not close the shop UI')
                after=call_command('proceed')
                checkpoint=advance({'kind':'leave','commands':['leave','proceed'],'raw_views':[raw,after]})
                if checkpoint['state']['phase']!='map': raise ValueError('shop exit did not reach map')
                row['identity']=game.identity
        except Exception as error:
            row.update(status='original_error',error=f'{type(error).__name__}: {error}')
        cleanup=directory/f'original-{i:05d}/cleanup.json'
        if cleanup.exists(): row['cleanup']=read_json(cleanup)
        rows.append(row);write_json(directory/'original.json.gz',rows)
        print(f'original {i+1}/{len(specs)}: {spec["name"]} {row.get("error","captured")}',flush=True)
    return rows


def replay(rows, executable, directory, presentation_frames=None, use_presentation=True):
    directory.mkdir(parents=True,exist_ok=False)
    report={'executable':str(executable.resolve()),'executable_sha256':sha256(executable),
        'projection_sha256':sha256(__file__),'reward_projection_sha256':sha256(Path(__file__).with_name('treasure.py')),
        'resynchronized':False,
        'declared_legacy_presentation_frames':presentation_frames,
        'presentation_tracking':use_presentation,
        'scope':'ten RNG streams, optional independently paired MathUtils and shared Collections state, initial-only RNG-relevant shop presentation with predeclared frame timing, wallet, HP, ordered deck/relics/potions, child rewards, grid candidates, stock/prices, shop actions and copy isolation',
        'gaps':['controlled pre-purchase stock; natural shop generation/entry excluded',
                'card UI open/close, reward return/reopen and shop room leave mapped to atomic native steps; original intermediate frames retained',
                'installed CommunicationMod omits the reward return button; existing oracle cancel_shop_reward clicks the visible native hitbox',
                'inventory_audit compares available shop items; unusable potion clicks remain command-domain differences and use the native public Shop guard, not an accepted GameAction',
                'complete legal UI domain and unmodeled private fields not equated; MathUtils requires declared initial state; installed-shop-v4 also requires the initial reward tip pool and shared Collections seed; installed-shop-v5 extends it with healing on equip and Dolly mirror timing; other callbacks and potion use excluded',
                'natural whole runs, save reload and vanilla reference'], 'results':[]}
    for i,row in enumerate(rows):
        result={'name':row['spec']['name'],'row_sha256':digest(row)}
        try:
            if row.get('status')=='original_error': result.update(status='original_error',error=row['error'])
            else:
                case=directory/f'case-{i:05d}';case.mkdir()
                initial=row['views'][0]['state']
                clocks=row['spec'].get('action_frames')
                frames=(clocks.get('CARD') if clocks is not None else row['spec'].get('presentation_frames',presentation_frames)) if use_presentation else None
                request={'spec':row['spec'],'pools':row['setup']['pools'],
                    'initial_deck':initial['deck'],'initial_relics':initial['relics'],
                    'steps':[{k:v for k,v in s.items() if k not in ('raw_views','command_frames')} for s in row['steps']]}
                if frames is not None:request['initial_presentation']=presentation_input(row['views'][0],frames,clocks)
                write_json(case/'input.json',request)
                run=subprocess.run([str(executable.resolve()),str(case/'input.json')],capture_output=True,text=True,timeout=20)
                (case/'stdout.json').write_text(run.stdout);(case/'stderr.log').write_text(run.stderr);result['exit']=run.returncode
                if run.returncode: result.update(status='worker_error',error=run.stderr)
                else:
                    expected={'views':[comparison_state(v,frames is not None,clocks is not None and 'REMOVE' in clocks,
                                       clocks is not None and 'REWARD_RETURN' in clocks,clocks is not None and 'UPGRADE' in clocks)
                                       for v in row['views']]}
                    actual=read_json(case/'stdout.json');copies=actual.pop('copy_checks')
                    actual={'views':[project(v) for v in actual['views']]}
                    for check in copies:check['child_after']=project(check['child_after'])
                    diffs=differences(expected,actual);order=[];domains=[];rules=[]
                    for diff in diffs:
                        if category_order_difference(diff,expected,actual):order.append(diff)
                        elif unusable_potion_domain(diff,expected,actual):domains.append(diff)
                        else:rules.append(diff)
                    result.update(status='mismatch' if rules else ('observation_difference' if diffs else 'coverage_gap'),
                        differences=diffs,rule_differences=rules,reward_order_differences=order,potion_domain_differences=domains,
                        initial_match=expected['views'][0]==actual['views'][0],observed_match=not diffs,rule_fields_match=not rules,
                        expected=expected,actual=actual,copy_checks=copies)
        except Exception as error: result.update(status='adapter_error',error=f'{type(error).__name__}: {error}')
        report['results'].append(result)
    report['counts']={s:sum(r['status']==s for r in report['results']) for s in sorted({r['status'] for r in report['results']})}
    write_json(directory/'report.json',report);print(report['counts'],flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--oracle',type=Path);p.add_argument('--specs',type=Path)
    p.add_argument('--source',type=Path);p.add_argument('--executable',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--presentation-frames',type=int)
    p.add_argument('--without-presentation',action='store_true',help='baseline audit: compare game/RNG fields without attaching private presentation')
    a=p.parse_args()
    rows=capture(Path(__file__).resolve().parents[2],a.oracle,read_json(a.specs),a.out) if a.oracle else read_json(a.source)
    report=replay(rows,a.executable,a.out/'comparison' if a.oracle else a.out,a.presentation_frames,not a.without_presentation)
    raise SystemExit(int(any(r['status'] not in ('coverage_gap','observation_difference') for r in report['results'])))
