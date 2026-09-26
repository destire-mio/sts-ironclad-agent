"""P207: test legal upstream opportunities suggested by P206, not magic HP."""
import argparse
from pathlib import Path
import time
import traceback

import heart_entry_resource_probe as H
import heart_intervention_replay as I

M,E,D=H.M,H.E,H.D
DESIGN=dict(maximum_proposals_per_family=2,maximum_suffix_calls=14,maximum_replans=14,
            suffix_seconds=300,stage_seconds=1800)


def prepare(root,source):
    root.mkdir(parents=True)
    prior=E.read(source/'main/artifact-review.json')
    E.require(prior['status']=='passed' and prior['unresolved_faults']==0,'P206 not verified')
    source_plan=E.read(source/'protocol.json');origin=Path(source_plan['source'])
    assignments=E.read(source/'assignments-private.json')
    selected={r['seed'] for r in prior['intervention_rows'] if r['group']=='fatal' and r['full_hp_survived']}
    E.require(len(selected)==7,'unexpected fixed causal cohort')
    families=[]
    for assignment in assignments:
        seed=assignment['reference']['seed']
        if seed not in selected:continue
        x,run,prefix,_,_=H.P.state(origin,assignment)
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
        last_rest=None;immediate_event=None
        for index,step in enumerate(prefix):
            x.R.clock_input(gc,x.config)
            if step['kind']=='outside':
                acts=list(x.R.sts.get_legal_game_actions(gc));_,descs,_=x.A.build_choices(gc)
                bits=[int(a.bits) for a in acts];chosen=bits.index(step['action']);kind=x.R.kind(descs[chosen])
                if kind==x.A.AK_REST:
                    rest=[i for i,(a,d) in enumerate(zip(acts,descs)) if x.R.kind(d)==x.A.AK_REST and int(a.idx1)==0]
                    last_rest=dict(index=index,before=step['before'],hp=int(gc.cur_hp),max_hp=int(gc.max_hp),
                        act=int(gc.act),floor=int(gc.floor_num),chosen=step['action'],
                        action=bits[rest[0]] if rest and int(gc.cur_hp)<int(gc.max_hp) and rest[0]!=chosen else None,
                        options=[int(a.idx1) for a,d in zip(acts,descs) if x.R.kind(d)==x.A.AK_REST])
                if index==len(prefix)-1 and kind==x.A.AK_EVENT:
                    alternatives=[]
                    for i,(a,d) in enumerate(zip(acts,descs)):
                        if i==chosen or x.R.kind(d)!=x.A.AK_EVENT:continue
                        context=x.R.replay(seed,prefix[:index],x.config)
                        native=x.R.sts.GameAction(int(a.bits)&0xffffffff)
                        E.require(native.is_valid(context),'illegal source event alternative')
                        native.execute(context)
                        if context.screen_state!=x.R.sts.ScreenState.BATTLE and context.cur_hp>=gc.cur_hp:
                            alternatives.append(int(a.bits))
                    immediate_event=dict(index=index,before=step['before'],hp=int(gc.cur_hp),max_hp=int(gc.max_hp),
                        act=int(gc.act),floor=int(gc.floor_num),chosen=step['action'],event=gc.event_id_string,
                        alternatives=sorted(alternatives))
            x.R.replay_step(gc,step,x.config)
        x.R.clock_input(gc,x.config);E.require(x.R.fingerprint(gc)==assignment['before'],'upstream source root differs')
        proposals=[]
        if last_rest is not None and last_rest['action'] is not None:
            proposals.append(dict(reason='rest_at_last_actual_campfire_with_immediate_healing',
                                  **{k:last_rest[k] for k in ('index','before','action','act','floor')}))
        if immediate_event is not None:
            for action in immediate_event['alternatives']:
                proposals.append(dict(reason='decline_immediate_optional_combat_without_losing_HP',action=action,
                                      **{k:immediate_event[k] for k in ('index','before','act','floor')}))
        E.require(len(proposals)<=DESIGN['maximum_proposals_per_family'],'opportunity count exceeds fixed budget')
        families.append(dict(assignment=assignment,last_rest=last_rest,immediate_event=immediate_event,proposals=proposals))
    M.put(root/'assignments-private.json',families)
    bound=[Path(__file__),Path(I.__file__),Path(H.__file__),Path(M.__file__),
           root/'assignments-private.json',source/'protocol.json',source/'main/artifact-review.json',
           source/'main/legal-upstream-trace.json']
    plan=dict(experiment='P207',source=str(source),origin=str(origin),design=DESIGN,
        hashes={str(p):E.sha(p) for p in bound},
        cohort='Exactly7 P206 fatal roots whose artificial full-HP state survived under original MCTS. Outcome-enriched causal followup, never a win-rate estimate.',
        opportunities='At the last actual campfire before the fatal root, change to legal rest only if it immediately heals and differs from the source action. Additionally, if the action immediately preceding that root entered an optional event battle, test each legal alternative leaving that battle with no immediate HP loss. No map/threshold/earlier-campfire scan. Preserve families with no opportunity.',
        intervention='Replay original natural prefix, execute one legal different game action, then frozen parent NN and native MCTS to true terminal. No HP/state editing. Different upgrades, draws, RNG and later decisions caused by that choice are part of its total effect; not pure HP mediation.',
        verification='Every suffix full natural action replay; every Heart witness fresh-planned from natural start with this intervention consumed once. Raw attempts written before audits. All actions, RNG and final keys/twoBosses/ShieldSpear/Heart checked.',
        stopping='Execute every registered opportunity once; no event/HP/threshold/seed expansion. Legal wins are conditional causal witnesses, not a selected public strategy. A positive case must motivate a public learnable mechanism before any deployment test.',
        max_new_plans=28,policy_adoption=False,unseen_acceptance_games=0)
    M.put(root/'protocol.json',plan)
    print(dict(status='P207_prepared',families=len(families),proposals=sum(len(f['proposals']) for f in families),
               with_opportunity=sum(bool(f['proposals']) for f in families)),flush=True)


def execute(root):
    plan=E.read(root/'protocol.json');E.require(plan['design']==DESIGN,'P207 recipe changed')
    for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'P207 bound input changed')
    started=time.monotonic();rows=[];faults=[];suffixes=0;replans=0;simulations=0
    for family in E.read(root/'assignments-private.json'):
        assignment=family['assignment'];seed=assignment['reference']['seed'];folder=root/'families'/str(seed)
        folder.mkdir(parents=True);reports=[]
        x,source,_,_,_=H.P.state(Path(plan['origin']),assignment);parent=E.parent_model(x)
        for number,proposal in enumerate(family['proposals']):
            suffix_calls=0;replan_calls=0
            try:
                E.require(time.monotonic()-started<DESIGN['stage_seconds'],'P207 deadline')
                prefix=source['prefix'][:proposal['index']]
                gc=x.R.replay(seed,prefix,x.config);E.require(x.R.fingerprint(gc)==proposal['before'],'wrong intervention state')
                act=x.R.sts.GameAction(proposal['action']&0xffffffff);E.require(act.is_valid(gc),'illegal intervention')
                step=dict(kind='outside',before=proposal['before'],action=proposal['action']);act.execute(gc)
                suffixes+=1;suffix_calls+=1
                cfg=dict(x.config,max_steps=x.config['max_steps']-len(prefix)-1,episode_seconds=DESIGN['suffix_seconds'])
                run=x.R.rollout(seed,cfg,gc=gc,net=parent,record=True,record_samples=False)
                x.R.clock_input(gc,x.config)
                run.update(prefix=prefix+[step]+run['prefix'],terminal_fingerprint=x.R.fingerprint(gc),
                           engine_sha256=x.identity['engine_sha256'],checkpoint_sha256=x.identity['model_sha256'])
                M.put(folder/f'{number}-attempt.json.gz',run);simulations+=run['simulations']
                run['audit']=M.check_route(x,run);M.put(folder/f'{number}-run.json.gz',run)
                win=run['status']=='heart_win'
                if win:
                    replans+=1;replan_calls+=1
                    repeated=I.replan(x,parent,seed,dict(changes=[proposal],run=run),folder/f'{number}-replan-attempt.json.gz')
                    simulations+=repeated['simulations'];M.put(folder/f'{number}-replan.json.gz',repeated)
                report=dict(status='complete',seed=seed,proposal=proposal,heart=win,terminal=run['status'],
                            floor=run['floor'],act=run['act'],suffix_calls=suffix_calls,replan_calls=replan_calls)
            except Exception:
                report=dict(status='fault',seed=seed,proposal=proposal,error=traceback.format_exc(),
                            suffix_calls=suffix_calls,replan_calls=replan_calls)
                faults.append(report)
            M.put(folder/f'{number}-result.json',report);reports.append(report)
        row=dict(seed=seed,original_heart=False,proposals=len(family['proposals']),
                 complete=not any(r['status']=='fault' for r in reports),
                 conditional_heart=any(r.get('heart',False) for r in reports),reports=reports)
        M.put(folder/'result.json',row);rows.append(row)
        print({k:row[k] for k in ('seed','proposals','complete','conditional_heart')},flush=True)
    result=dict(status='incomplete_faults' if faults else 'complete',assigned_families=7,
        families_with_opportunity=sum(r['proposals']>0 for r in rows),proposals=sum(r['proposals'] for r in rows),
        conditional_heart_families=sum(r['conditional_heart'] for r in rows),faults=faults,
        suffix_calls=suffixes,replan_calls=replans,new_planning_calls=suffixes+replans,simulations=simulations,
        seconds=time.monotonic()-started,policy_adoption=False,unseen_acceptance_games=0,families=rows)
    M.put(root/'result.json',result);print({k:v for k,v in result.items() if k!='families'},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','run'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--source',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.source.resolve())
    else:execute(root)
