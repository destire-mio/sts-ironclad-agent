"""Replay original command logs without running or substituting a simulator."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.oracle import Original
from sim_patch.parity.core import read_json,write_json,differences,sha256
from steam.rng_preflight import seed_token


def projection(view):
    game=view['game']
    keys=('seed','act','floor','current_hp','max_hp','gold','keys','room_phase','screen_type')
    out={k:game[k] for k in keys if k in game}
    out['keys']=[view['ruby'],view['emerald'],view['sapphire']]
    card=lambda c:{k:c[k] for k in ('id','upgrades','misc','cost','base_cost','free_to_play_once','base_damage') if k in c}
    out['deck']=[card(c) for c in game['deck']]
    out['relics']=[{k:r[k] for k in ('id','counter')} for r in game['relics']]
    out['potions']=[p['id'] for p in game['potions']]
    out['rng']=game['full_rng_state']['streams']
    run=view.get('live_run')
    if run:
        out['run']={k:run[k] for k in ('x','y','room','boss','bossList','monsterList','eliteMonsterList',
            'eventList','shrineList','specialOneTimeEventList','pools','card_rarity_factor','potion_chance',
            'purge_cost','event_chances') if k in run}
        out['run']['deck']=[{**card(c),'bottled':c['bottled']} for c in run['deck']]
        def reward(r):
            result={k:r[k] for k in ('type','done','relic','potion','gold') if k in r}
            if 'cards' in r:result['cards']=[card(c) for c in r['cards']]
            return result
        out['run']['rewards']=[reward(r) for r in run['rewards']]
        out['run']['room_rewards']=[reward(r) for r in run['room_rewards']]
    out['map']=game['map']
    screen=game['screen_state']
    out['screen']={k:screen[k] for k in ('event_id','event_name','first_node_chosen','boss_available',
        'for_upgrade','for_purge','for_transform','num_cards','any_number','can_pick_zero',
        'purge_available','purge_cost') if k in screen}
    for key in ('cards','selected_cards'):
        if key in screen:out['screen'][key]=[card(c) for c in screen[key]]
    for key in ('relics','potions'):
        if key in screen:out['screen'][key]=[{k:c[k] for k in ('id','price') if k in c} for c in screen[key]]
    if game['screen_type']=='EVENT':
        out['screen']['options']=[{k:o[k] for k in ('choice_index','disabled') if k in o} for o in screen['options']]
    combat=game.get('combat_state')
    if combat:
        out['combat']={k:combat[k] for k in ('turn','cards_discarded_this_turn','cards_played_this_turn') if k in combat}
        for pile in ('hand','draw_pile','discard_pile','exhaust_pile'):
            out['combat'][pile]=[card(c) for c in combat[pile]]
        def creature(c):
            result={k:c[k] for k in ('id','current_hp','max_hp','block','energy','move_id','last_move_id','half_dead','is_gone') if k in c}
            if 'id' in c:result['last_move_id']=c.get('last_move_id',-1)
            result['powers']=[{k:p[k] for k in ('id','amount','counter','damage') if k in p} for p in c['powers']]
            return result
        out['combat']['player']=creature(combat['player'])
        out['combat']['monsters']=[creature(c) for c in combat['monsters']]
    return out


def run(args):
    args.out.mkdir(parents=True,exist_ok=False)
    initial=read_json(args.source/'initial.json.gz');seed=initial['game']['seed'];rows=[]
    with Original(args.oracle,args.out/'original',ROOT) as original:
        original.call('command',command='start ironclad 20 '+seed_token(seed))
        original.call('live_rng_restore',state=initial['game']['full_rng_state'])
        paths=sorted(args.source.glob('step-*.json.gz'))
        for index,path in enumerate(paths[:args.limit] if args.limit else paths):
            expected=read_json(path)
            if expected['kind']=='save_load':actual=original.call('live_reload',timeout_seconds=180)
            else:actual=original.call('command',command=expected['command'],play_time_seconds=expected['after']['rule_input_play_time'])
            before,after=expected['before']['game'],expected['after']['game']
            if after.get('room_phase')=='COMBAT' and before.get('room_phase')!='COMBAT':
                try:original.call('live_checkpoint')
                except RuntimeError:pass  # No checkpoint is needed unless the log contains an SL.
            diff=differences(projection(expected['after']),projection(actual))
            shared=[d for d in diff if d['path'].startswith(('/rng/MathUtils.random/','/rng/Collections.r/'))]
            rules=[d for d in diff if d not in shared]
            row=dict(index=index,command=expected['command'],source_sha256=sha256(path),differences=diff,
                     rule_differences=rules,shared_rng_differences=shared)
            rows.append(row);write_json(args.out/f'step-{index:05}.json.gz',dict(**row,actual=actual))
            if rules or (args.strict_all_rng and diff):break
    rule_passed=bool(rows) and all(not r['rule_differences'] for r in rows) and len(rows)==len(paths[:args.limit] if args.limit else paths)
    rng_passed=bool(rows) and all(not r['differences'] for r in rows)
    result=dict(passed=rule_passed and (rng_passed or not args.strict_all_rng),commands=len(rows),
                rule_replay_passed=rule_passed,all_rng_replay_passed=rule_passed and rng_passed,
                shared_rng_divergent_steps=sum(bool(r['shared_rng_differences']) for r in rows),
                strict_all_rng=args.strict_all_rng,requested_limit=args.limit,
                completed_natural_runs=0,source=str(args.source),projection_sha256=sha256(Path(__file__)),
                coverage='rule state, rewards, map, pools, encounter/event lists, selections and all persistent RNGs',
                gaps=['cross-JVM card UUIDs','all event/monster/card private fields','frame-by-frame visual equivalence'],steps=rows)
    write_json(args.out/'result.json',result)
    print({k:v for k,v in result.items() if k!='steps'})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','oracle','out'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--limit',type=int,default=0);p.add_argument('--strict-all-rng',action='store_true');a=p.parse_args()
    raise SystemExit(0 if run(a)['passed'] else 2)
