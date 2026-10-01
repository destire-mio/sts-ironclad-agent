"""Run the frozen P300 arm in an isolated licensed original-game instance.

Every Java command is persisted with its before/after state. Execution faults
remain faults, never losses. Use replay_original.py to replay saved commands.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.core import write_json,read_json,sha256,differences
from sim_patch.parity.oracle import Original
from steam.live_search import LiveSearch
from steam.live_policy import LivePolicy
from steam.rng_preflight import seed_token
from steam.rng_contract import validate


def transport(view, policy):
    g=view['game'];screen=g['screen_type'];available=view['available_commands']
    if screen=='EVENT':
        event=g['screen_state']['event_id'];fields=view['live_run']['event_fields'];phase=fields.get('screen',fields.get('curScreen'))
        # Native resolves the Wheel on the first click. Java still needs Spin,
        # Prize and Leave clicks, even when native is already on REWARDS.
        # Replaying those as event actions rerolls the Wheel and can consume
        # the continuation needed to leave the real relic reward screen.
        # The portal rule has already entered the native boss battle. Java
        # still has its descriptive Leave click before opening that battle.
        if event=='SecretPortal' and phase in ('ACCEPT','LEAVE'):
            return 'choose 0'
        # Spire Heart belongs to Java's Act-3 transition, not its event choices.
        # Native afterBattle has already decided Act 4 from the three keys.
        if event=='Spire Heart' and view['live_run']['room']=='VictoryRoom':
            options=[o for o in g['screen_state']['options'] if not o['disabled']]
            if len(options)!=1:
                raise ValueError('Spire Heart transition requires one original acknowledgement')
            return 'choose '+str(options[0]['choice_index'])
        if event=='Wheel of Change' and (fields.get('startSpin') or phase in ('COMPLETE','LEAVE')):
            return 'choose 0'
        if (event in ('Falling','SensoryStone','Designer','Colosseum') and phase=='INTRO') or (event=='Knowing Skull' and phase=='INTRO_1'):
            return 'choose 0'
        if event=='Nest' and view['live_run']['event_fields'].get('screenNum')==0:return 'choose 0'
    if screen=='EVENT' and g['screen_state']['event_id']=='Neow Event':
        if view['live_run']['event_fields']['screenNum']!=3:return 'choose 0'
    if screen=='EVENT' and policy.gc.screen_state in (policy.sts.ScreenState.MAP_SCREEN,policy.sts.ScreenState.CARD_SELECT):
        opts=[o for o in g['screen_state']['options'] if not o['disabled']]
        if len(opts)==1:return 'choose 0'
    if screen=='SHOP_ROOM':
        return 'proceed' if policy.gc.screen_state==policy.sts.ScreenState.MAP_SCREEN else 'choose 0'
    if screen in ('GRID','HAND_SELECT') and 'confirm' in available and policy.gc.screen_state!=policy.sts.ScreenState.CARD_SELECT:
        return 'confirm'
    if screen in ('NONE','COMPLETE') and g['room_phase']!='COMBAT' and 'proceed' in available:return 'proceed'
    if screen=='REST' and not g.get('choice_list') and 'proceed' in available:return 'proceed'
    if screen=='CHEST' and not g.get('choice_list') and 'proceed' in available:return 'proceed'
    if screen=='CHEST' and policy.gc.screen_state==policy.sts.ScreenState.BOSS_RELIC_REWARDS:return 'choose 0'
    return None


def run(args):
    args.out.mkdir(parents=True,exist_ok=False)
    files=[*ROOT.joinpath('steam').glob('live_*.py'),ROOT/'steam/steam_mcts.py',ROOT/'steam/selection_import.py',ROOT/'steam/rng_contract.py',ROOT/'steam/replay_original.py',
           *ROOT.joinpath('steam/native').glob('*'),*ROOT.joinpath('sim_patch/parity').glob('*.py'),
           *ROOT.joinpath('sim_patch/parity/java').glob('*.java'),
           *ROOT.joinpath('steam/state_export_mod/src/steamstateexport').glob('*.java')]
    hashes={}
    for f in files:
        dst=args.out/'capture-sources'/f.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,dst)
        hashes[str(f.relative_to(ROOT))]=sha256(dst)
    write_json(args.out/'capture-code.json',hashes)
    result=dict(seed=args.seed,arm='sims32+boss12+rest+reuse+svsel+svcard',status='running',
        completed_natural_runs=0,save_load_count=0,resynchronizations=0,divergences=[],battles=[],
        runtime_manifest_sha256=sha256(args.runtime/'live-manifest.json'),capture_code_sha256=sha256(args.out/'capture-code.json'),
        steps=0,replayed_commands=0,simulations_per_round=args.simulations,boss_multiplier=12.,reload_policy=dict(max_per_battle=args.max_reloads_per_battle,
        hp_shortfall_threshold=args.reload_on_hp_shortfall))
    started=time.monotonic();view=None;index=0
    prefix=getattr(args,'replay_prefix',None)
    prefix_paths=sorted(prefix.glob('step-*.json.gz')) if prefix else []
    def publish():
        result['seconds']=time.monotonic()-started
        write_json(args.out/'result.json',result)
    try:
        if prefix:
            source=read_json(prefix/'result.json')
            if source['seed']!=args.seed or source['runtime_manifest_sha256']!=result['runtime_manifest_sha256']:
                raise ValueError('replay prefix requires identical seed and frozen runtime')
            budget=source.get('simulations_per_round')
            if budget is None and (prefix.parent/'manifest.json').exists():
                budget=read_json(prefix.parent/'manifest.json')['simulations']
            if budget!=args.simulations:raise ValueError('replay prefix search budget differs or is unknown')
            result['replay_prefix']=dict(source=str(prefix),result_sha256=sha256(prefix/'result.json'),
                requested_commands=len(prefix_paths),verified_commands=0,shared_rng_divergent_steps=0)
        search=LiveSearch(args.runtime,ROOT,args.simulations,12.)
        policy=LivePolicy(search,args.seed)
        with Original(args.oracle,args.out/'original',ROOT) as original:
            view=original.call('command',command='start ironclad 20 '+seed_token(args.seed))
            if prefix:
                view=original.call('live_rng_restore',state=read_json(prefix/'initial.json.gz')['game']['full_rng_state'])
            write_json(args.out/'initial.json.gz',view)
            def command(cmd,kind,**metadata):
                nonlocal index,view
                before=view
                expected=read_json(prefix_paths[index]) if index<len(prefix_paths) else None
                options={}
                if expected:
                    if expected['command']!=cmd:raise ValueError('replay prefix command differs at '+str(index))
                    options['play_time_seconds']=expected['after']['rule_input_play_time']
                view=(original.call('live_reload',timeout_seconds=180) if kind=='save_load' else
                      original.call('command',command=cmd,**options))
                errors=validate(view,require_oracle=True) if 'game' in view else []
                row=dict(index=index,command=cmd,kind=kind,before=before,after=view,**metadata)
                if expected:
                    from steam.replay_original import projection
                    diff=differences(projection(expected['after']),projection(view))
                    shared=[d for d in diff if d['path'].startswith(('/rng/MathUtils.random/','/rng/Collections.r/'))]
                    rules=[d for d in diff if d not in shared]
                    row['prefix_replay']=dict(source_sha256=sha256(prefix_paths[index]),rule_differences=rules,shared_rng_differences=shared)
                    write_json(args.out/f'step-{index:05}.json.gz',row)
                    if rules:raise ValueError('original replay prefix differs at '+str(index)+': '+repr(rules[:8]))
                    result['replay_prefix']['verified_commands']+=1
                    result['replayed_commands']+=1
                    result['replay_prefix']['shared_rng_divergent_steps']+=bool(shared)
                if 'game' in view:
                    old=before['game']['full_rng_state']['streams'];new=view['game']['full_rng_state']['streams']
                    row['rng_audit']={name:dict(changed=old[name]!=new[name],before=old[name],after=new[name]) for name in new}
                write_json(args.out/f'step-{index:05}.json.gz',row)
                index+=1;result['steps']=index
                if errors:raise ValueError('RNG export changed: '+repr(errors))
                return before,row
            in_battle=False
            for decision in range(args.max_decisions):
                if 'game' not in view:raise ValueError('left dungeon without a terminal observation')
                g=view['game']; screen=g['screen_type']
                if g['seed']!=args.seed:raise ValueError('original seed changed')
                if g['current_hp']<=0 or screen in ('GAME_OVER','VICTORY'):
                    won=g['current_hp']>0 and g['act']==4
                    result.update(status='win' if won else 'loss' if g['current_hp']<=0 else 'act3_only',
                                  completed_natural_runs=1,floor=g['floor'],act=g['act'],hp=g['current_hp'])
                    break
                combat=g.get('room_phase')=='COMBAT' and 'combat_state' in g
                if combat:
                    if not in_battle:
                        policy.sync(view)
                        search.actions.clear();in_battle=True
                        result['battles'].append(dict(floor=g['floor'],act=g['act'],hp=g['current_hp'],
                            monsters=[m['id'] for m in g['combat_state']['monsters']]))
                        checkpoint_view=view;checkpoint_gc=policy.F.copy_game(policy.gc)
                        try:
                            checkpoint=original.call('live_checkpoint')
                            write_json(args.out/f"checkpoint-{g['floor']:02}.json.gz",checkpoint)
                            result['battles'][-1]['checkpoint_available']=True
                        except RuntimeError as error:
                            # Some event fights have no autosave of this exact
                            # encounter. Continue from authority, never fake SL.
                            result['battles'][-1].update(checkpoint_available=False,checkpoint_error=str(error))
                    if not search.actions:
                        replay_plan=prefix/f'plan-{search.plans+1:04}.json' if prefix and index<len(prefix_paths) else None
                        plan=search.replan(view,read_json(replay_plan) if replay_plan else None)
                        if replay_plan:plan['source_plan_sha256']=sha256(replay_plan)
                        write_json(args.out/f'plan-{search.plans:04}.json',plan)
                        if result['battles'][-1].get('plan') is not None:result['resynchronizations']+=1
                        result['battles'][-1]['plan']=search.plans
                        result['battles'][-1]['predicted_outcome']=plan['outcome']
                        result['battles'][-1]['predicted_hp']=plan['hp']
                    action,cmd=search.next_action(view)
                    before,row=command(cmd,'combat',action_bits=int(action.bits) if action else None,plan=search.plans)
                    comparison=search.accept(action,view)
                    if search.confirmation(view):
                        _,row=command('confirm','combat_ack',plan=search.plans)
                        comparison=search.accept(None,view)
                    left=view['game']['current_hp']<=0 or view['game'].get('room_phase')!='COMBAT' or 'combat_state' not in view['game']
                    if left:
                        in_battle=False
                        expected_outcome=search.sts.Outcome.PLAYER_VICTORY if view['game']['current_hp']>0 else search.sts.Outcome.PLAYER_LOSS
                        if search.battle.outcome==expected_outcome:
                            search.battle.exit_battle(policy.gc)
                            outside=policy.compare(view,before)
                            comparison['exit_comparison']=outside
                            comparison['differences']+=outside['differences']
                        else:
                            search.native.recover_run_after_battle(search.battle,policy.gc,view['game']['current_hp']>0)
                            comparison['run_continuation_resynchronized']=True
                            result['resynchronizations']+=1
                            if view['game']['current_hp']>0 and view['game']['screen_type'] not in ('GAME_OVER','VICTORY'):policy.sync(view)
                        result['battles'][-1].update(hp_after=view['game']['current_hp'],outcome='won' if view['game']['current_hp']>0 else 'lost')
                else:
                    in_battle=False
                    cmd=transport(view,policy)
                    if cmd:
                        before,row=command(cmd,'transport')
                        comparison={'differences':[],'gaps':['UI acknowledgement; full before/after state retained']}
                    else:
                        action,commands,detail=policy.choose(view)
                        write_json(args.out/f'decision-{decision:05}.json.gz',detail)
                        before=view
                        for cmd in commands:
                            _,row=command(cmd,'outside',action_bits=int(action.bits),decision=decision)
                        action.execute(policy.gc)
                        # One native action can require several original UI
                        # acknowledgements (smith confirm, Serpent Continue,
                        # shop leave). Compare after the rule action commits.
                        for acknowledgement in range(12):
                            ack=transport(view,policy)
                            if ack is None:break
                            _,row=command(ack,'outside_ack',action_bits=int(action.bits),decision=decision)
                        else:raise RuntimeError('outside UI acknowledgement loop')
                        if view['game'].get('room_phase')=='COMBAT':
                            predicted=search.sts.BattleContext();predicted.init(policy.gc)
                            comparison=search.comparator.compare_battle(view,predicted)
                        else:comparison=policy.compare(view,before)
                row['comparison']=comparison
                write_json(args.out/f"step-{row['index']:05}.json.gz",row)
                if comparison['differences']:
                    divergence=dict(step=row['index'],floor=view['game']['floor'],act=view['game']['act'],
                        command=row['command'],kind=row['kind'],differences=comparison['differences'],
                        cards=[c['id'] for c in before['game'].get('combat_state',{}).get('hand',[])],
                        relics=[r['id'] for r in before['game']['relics']],
                        monsters=[m['id'] for m in before['game'].get('combat_state',{}).get('monsters',[])])
                    result['divergences'].append(divergence)
                    battle=result['battles'][-1] if combat else None
                    shortfall=max([0]+[d['simulator']-d['original'] for d in comparison['differences']
                        if d['path'] in ('/player/hp','/run/hp') and isinstance(d.get('original'),(int,float))
                        and isinstance(d.get('simulator'),(int,float))])
                    if (battle and battle['checkpoint_available'] and args.reload_on_hp_shortfall>0 and
                        shortfall>=args.reload_on_hp_shortfall and battle.get('reloads',0)<args.max_reloads_per_battle):
                        battle.setdefault('failed_attempts',[]).append(dict(step=row['index'],hp=view['game']['current_hp'],
                            shortfall=shortfall,plan=battle['plan']))
                        _,reload_row=command('live_reload','save_load',reason_step=row['index'])
                        result['save_load_count']+=1;battle['reloads']=battle.get('reloads',0)+1
                        restored=search.comparator.import_battle(view)
                        check=search.comparator.compare_battle(checkpoint_view,restored)
                        if check['differences']:raise ValueError('SL combat state differs from checkpoint: '+repr(check['differences']))
                        if view['game']['full_rng_state']['streams']!=checkpoint_view['game']['full_rng_state']['streams']:
                            raise ValueError('SL RNG streams differ from checkpoint')
                        reload_row['comparison']=check;write_json(args.out/f"step-{reload_row['index']:05}.json.gz",reload_row)
                        policy.gc=policy.F.copy_game(checkpoint_gc);search.actions.clear();in_battle=True
                        battle.pop('hp_after',None);battle.pop('outcome',None)
                    if args.stop_on_divergence:
                        result['status']='divergence';break
                publish()
                print(json.dumps(dict(step=row['index'],floor=view['game']['floor'],hp=view['game']['current_hp'],screen=view['game']['screen_type'],
                    command=row['command'],diffs=len(comparison['differences'])),ensure_ascii=False),flush=True)
            else:raise RuntimeError('whole-run decision limit')
            write_json(args.out/'terminal.json.gz',view)
    except BaseException as error:
        result.update(status='fault',error=repr(error),traceback=traceback.format_exc())
        if view:write_json(args.out/'fault-view.json.gz',view)
        raise
    finally:publish()
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',type=Path,required=True);p.add_argument('--oracle',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--seed',type=int,default=5100000000)
    p.add_argument('--simulations',type=int,default=32000);p.add_argument('--max-decisions',type=int,default=6000)
    p.add_argument('--stop-on-divergence',action='store_true')
    p.add_argument('--replay-prefix',type=Path,help='verified prior commands and plans of the same seed/runtime, then continue')
    p.add_argument('--reload-on-hp-shortfall',type=int,default=0,help='0 disables automatic SL; otherwise minimum extra HP lost')
    p.add_argument('--max-reloads-per-battle',type=int,default=1)
    args=p.parse_args();args.runtime=args.runtime.resolve();args.out=args.out.resolve()
    r=run(args);print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['completed_natural_runs'] else 2)
