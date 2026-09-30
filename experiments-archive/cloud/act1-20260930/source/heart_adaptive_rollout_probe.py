"""P205: controlled tactical capability, not an adopted full-game policy."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
import math
import multiprocessing
from pathlib import Path
import time
import traceback

import heart_adaptive_rollouts as A
import heart_compositional_capability as M

E,D=M.E,M.D
DESIGN=dict(fatal=16,surviving=8,workers=8,seconds=7200,preflight_searches=8,
            preflight_rollouts=64,maximum_main_search_calls=96,maximum_controls=24,
            maximum_suffix_calls=48,maximum_full_replans=48)
ARMS=('sampling','adaptive')


def prepare(root, runtime):
    root.mkdir(parents=True)
    x=D.runtime(str(runtime)); refs=E.read(runtime.parent/'fit-references.json')
    old=Path(E.read(root.parent/'p201-temporal-credit-20260924-01/protocol.json')['source'])
    role_path=old/'roles-private.json';excluded=set(E.read(role_path)['evaluation'])
    eligible={'fatal':[],'surviving':[]};skipped=[]
    for ref in refs:
        if ref['seed'] in excluded or ref['act']<3:continue
        group='surviving' if ref['status']=='heart_win' else 'fatal' if ref['status']=='death' else None
        if group is None:continue
        E.require(E.sha(ref['path'])==ref['sha256'],'parent source changed')
        run=E.read(ref['path'])
        if run['prefix'][-1]['kind']!='battle':skipped.append(ref['seed']);continue
        eligible[group].append(dict(reference=ref,group=group,index=len(run['prefix'])-1,
            before=run['prefix'][-1]['before'],root_control=run['prefix'][-1]))
    selected=[]
    for group in ('fatal','surviving'):
        ordered=sorted(eligible[group],key=lambda r:M.digest(['P205-root',group,r['reference']['seed']]))
        E.require(len(ordered)>=DESIGN[group],'insufficient P205 source roots')
        selected.extend(ordered[:DESIGN[group]])
    M.put(root/'assignments-private.json',selected)
    paths=[Path(A.__file__),Path(M.__file__),Path(D.__file__),Path(E.__file__),
           root/'assignments-private.json',role_path,runtime.parent/'fit-references.json',
           runtime/'identity.json',runtime/'manifest.json',runtime/'config.json']
    plan=dict(experiment='P205',runner_sha256=E.sha(__file__),recipe=A.RECIPE,design=DESIGN,
        runtime=str(runtime),hashes={str(p):E.sha(p) for p in paths},
        selection='Original1536 fit families, excluding E191128 evaluation families. Terminal battle of parent Act3/4 deaths or Heart wins, then fixed SHA256 order P205-root/group/seed.16 fatal and8 surviving roots. Outcome-enriched diagnosis, not a natural win-rate cohort.',
        eligible={k:len(v) for k,v in eligible.items()},nonbattle_terminal_exclusions=skipped,
        intervention='One root-level complete-plan search,8000 rollouts or24000 for boss encounter types. Native BattleContext clones preserve the exact game state and RNG. No new engine or game rules.',
        arms=dict(control='Native MCTS complete-battle resolver at original8000/boss3; must reproduce recorded battle and terminal.',
            sampling='Complete stochastic plans, uniform legal actions except END_TURN weight.1 when cards are playable.',
            adaptive='Two balanced NRPA levels, group count=floor(sqrt(rollout budget)), alpha1, exact same total rollouts, base distribution and terminal score as sampling. Inner policy is copied; only best sequence updates its parent.'),
        score='Lexicographic survival,HP,potion count,-turn. Complete losses rank by remaining enemy HP ratio,then enemy count and turns; incomplete500-turn branches rank last. This MC/NRPA score differs from MCTS; only their mutual comparison isolates adaptation.',
        action_code='Ply, legal native action bits, acted-on card identity/upgrade or potion identity. Distinct actions remain distinct; ply prevents later decisions sharing the selected code. Local search parameters never leave this root.',
        verification='Every returned plan replayed with regenerated menus and native legality. All surviving searches cold-repeated; full Heart witness repeats recompute parent NN/MCTS from natural start and rerun this single conditional combat intervention. Source and game RNG immutable during search.',
        continuation='For a surviving selected plan, execute from the original root then frozen parent to true terminal. Keep fatal and surviving controls separate. This conditional witness is not a public deployed policy.',
        mechanism_gate='At least4/16 fatal roots rescued by adaptive, and at least3 more than fixed sampling on those same roots, zero unresolved faults. This opens design of a full-game search candidate; it does not prove adoption or50percent. Report complete Heart conversions separately.',
        failure_rule='Close this exact action code, nesting, bias and score if the gate fails; no alpha/depth/temperature/iteration/extra-root sweep.',
        accounting='Rollout counts are not equal CPU time. Count transitions, adaptation updates, wall time, suffix calls, full replans and every fault. Original native MCTS can perform multiple searches per battle; its actual count is reported.',
        source='https://www.ijcai.org/papers11/Papers/IJCAI11-115.pdf',
        policy_adoption=False,unseen_acceptance_games=0)
    M.put(root/'protocol.json',plan)
    print(dict(status='adaptive_probe_prepared',eligible=plan['eligible'],assigned=len(selected)),flush=True)


@lru_cache(maxsize=1)
def checked(root):
    plan=E.read(root/'protocol.json')
    E.require(E.sha(__file__)==plan['runner_sha256'] and plan['recipe']==A.RECIPE and plan['design']==DESIGN,'P205 runner or recipe changed')
    for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'P205 bound input changed: '+path)
    return plan


def state(root, assignment):
    plan=checked(root);x=D.runtime(plan['runtime']);ref=assignment['reference']
    E.require(E.sha(ref['path'])==ref['sha256'],'P205 parent reference changed')
    source=E.read(ref['path'])
    E.require(source['checkpoint_sha256']==x.identity['model_sha256'] and source['engine_sha256']==x.identity['engine_sha256'],'P205 parent identity differs')
    prefix=source['prefix'][:assignment['index']]
    gc=x.R.replay(ref['seed'],prefix,x.config)
    E.require(x.R.fingerprint(gc)==assignment['before'] and gc.act>=3 and gc.screen_state==x.R.sts.ScreenState.BATTLE,'P205 root changed')
    battle=x.R.sts.BattleContext();battle.init(gc)
    return x,source,prefix,gc,battle


def seed_for(seed):return int(M.digest(['P205-search',seed])[:16],16)


def search_record(x, battle, seed, arm, budget, progress_path):
    before=A.signature(battle);started=time.monotonic()
    def progress(values):M.put(progress_path,dict(status='searching',arm=arm,budget=budget,seconds=time.monotonic()-started,**values))
    search=A.Search(x.R.sts,battle,seed_for(seed),progress=progress)
    try:
        best=search.run(budget,arm=='adaptive');final=A.verify(x.R.sts,battle,best)
    except Exception:
        M.put(progress_path,dict(status='fault',arm=arm,budget=budget,seconds=time.monotonic()-started,
            rollouts=search.rollouts,transitions=search.transitions,updates=search.updates,partial_paths=search.partial_paths,error=traceback.format_exc()))
        raise
    E.require(before==A.signature(battle),'P205 search changed root')
    result=dict(arm=arm,budget=budget,rollouts=search.rollouts,transitions=search.transitions,
        updates=search.updates,partial_paths=search.partial_paths,seconds=time.monotonic()-started,
        value=list(best.value),actions=best.actions,outcome=best.outcome,hp=best.hp,turns=best.turn,
        root_signature=before,terminal_signature=A.signature(final),
        survived=best.value[0]==1.,frames_sha256=M.digest(best.frames))
    return result,final


def battle_step(assignment,search):
    return dict(kind='battle',before=assignment['before'],actions=search['actions'],
                simulations=search['rollouts'],turns=search['turns'],outcome=search['outcome'],
                search_algorithm='P205_'+search['arm'])


def worker(job):
    root=Path(job['root']);assignment=job['assignment'];seed=assignment['reference']['seed'];arm=job['arm'];phase=job['phase']
    folder=root/phase/arm/str(seed);folder.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();search_calls=0;suffix_calls=0;full_replans=0;controls=0;costs=[]
    def status():M.put(folder/'status.json',dict(status='running',search_calls=search_calls,suffix_calls=suffix_calls,full_replans=full_replans,controls=controls))
    try:
        plan=checked(root);E.require(time.monotonic()-job['start']<DESIGN['seconds'],'P205 study deadline')
        x,source,prefix,gc,battle=state(root,assignment);expected=source['prefix'][assignment['index']]
        if arm=='control':
            controls+=1;status()
            control=dict(x.R.sts.resolve_battle_recorded(gc,x.config['simulations'],x.config['boss_multiplier']))
            M.put(folder/'attempt.json',control)
            E.require(all(control[k]==expected[k] for k in ('actions','simulations','turns','outcome')),'P205 native control differs')
            x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,source)
            report=dict(status='complete',seed=seed,arm=arm,group=assignment['group'],controls=controls,
                        simulations=control['simulations'],seconds=time.monotonic()-started)
        else:
            budget=DESIGN['preflight_rollouts'] if phase=='preflight' else A.RECIPE['base_rollouts']*(3 if gc.encounter.name in A.BOSSES else 1)
            search_calls+=1;status();searched,final=search_record(x,battle,seed,arm,budget,folder/'search-1-progress.json');costs.append(searched)
            M.put(folder/'search-1.json.gz',searched)
            E.require(x.R.fingerprint(gc)==assignment['before'],'P205 search mutated game root')
            heart=None;run=None
            if phase=='main' and searched['survived']:
                final.exit_battle(gc);suffix_calls+=1;status()
                config=dict(x.config,max_steps=x.config['max_steps']-len(prefix)-1)
                run=x.R.rollout(seed,config,gc=gc,net=E.parent_model(x),record=True,record_samples=False)
                x.R.clock_input(gc,x.config)
                run.update(prefix=prefix+[battle_step(assignment,searched)]+run['prefix'],terminal_fingerprint=x.R.fingerprint(gc),
                           engine_sha256=x.identity['engine_sha256'],checkpoint_sha256=x.identity['model_sha256'])
                M.put(folder/'suffix-attempt.json.gz',run)
                run['audit']=M.check_route(x,run);heart=run['status']=='heart_win';M.put(folder/'run.json.gz',run)
            if phase=='preflight' or searched['survived']:
                search_calls+=1
                if phase=='main' and heart:
                    full_replans+=1;status();original=x.R.sts.resolve_battle_recorded;used=[]
                    def override(live_gc,simulations,boss_multiplier):
                        if not used and x.R.fingerprint(live_gc)==assignment['before']:
                            fresh=x.R.sts.BattleContext();fresh.init(live_gc)
                            repeated,ending=search_record(x,fresh,seed,arm,budget,folder/'search-2-progress.json');costs.append(repeated);used.append(repeated)
                            M.put(folder/'search-2.json.gz',repeated);ending.exit_battle(live_gc)
                            return {k:v for k,v in battle_step(assignment,repeated).items() if k not in ('kind','before')}
                        return original(live_gc,simulations,boss_multiplier)
                    x.R.sts.resolve_battle_recorded=override
                    try:
                        fresh_gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
                        rerun=x.R.rollout(seed,x.config,gc=fresh_gc,net=E.parent_model(x),record=True,record_samples=False)
                        x.R.clock_input(fresh_gc,x.config);rerun['terminal_fingerprint']=x.R.fingerprint(fresh_gc)
                        M.put(folder/'replan-attempt.json.gz',rerun)
                        rerun['audit']=M.check_route(x,rerun)
                    finally:x.R.sts.resolve_battle_recorded=original
                    E.require(len(used)==1,'P205 conditional intervention not reached')
                    repeated=used[0]
                    E.require(rerun['prefix']==run['prefix'] and rerun['terminal_fingerprint']==run['terminal_fingerprint'],'P205 full witness replan differs')
                    M.put(folder/'replan.json.gz',rerun)
                else:
                    status();repeated,_=search_record(x,battle,seed,arm,budget,folder/'search-2-progress.json');costs.append(repeated)
                    M.put(folder/'search-2.json.gz',repeated)
                E.require(all(repeated[k]==searched[k] for k in ('actions','value','outcome','hp','turns','terminal_signature','frames_sha256','transitions','updates')),'P205 repeated search differs')
            report=dict(status='complete',seed=seed,arm=arm,group=assignment['group'],phase=phase,
                survived=searched['survived'],heart=heart,search_calls=search_calls,suffix_calls=suffix_calls,full_replans=full_replans,
                rollouts=sum(c['rollouts'] for c in costs),transitions=sum(c['transitions'] for c in costs),updates=sum(c['updates'] for c in costs),
                partial_paths=sum(c['partial_paths'] for c in costs),search_seconds=sum(c['seconds'] for c in costs),seconds=time.monotonic()-started)
    except Exception:
        partial=[]
        for i in range(len(costs)+1,search_calls+1):
            path=folder/f'search-{i}-progress.json'
            if path.exists():partial.append(E.read(path))
        report=dict(status='fault',seed=seed,arm=arm,group=assignment['group'],phase=phase,search_calls=search_calls,
            controls=controls,suffix_calls=suffix_calls,full_replans=full_replans,error=traceback.format_exc(),seconds=time.monotonic()-started,
            recorded_rollouts=sum(c['rollouts'] for c in costs+partial),
            transitions=sum(c['transitions'] for c in costs+partial),updates=sum(c['updates'] for c in costs+partial),
            limits='Includes progress ledgers for unfinished searches; a process crash can leave unrecorded work. This is not a game loss.')
    M.put(folder/'result.json',report);return report


def execute(root,phase):
    checked(root);started=time.monotonic();assignments=E.read(root/'assignments-private.json');folder=root/phase;folder.mkdir()
    def job(a,arm):return dict(root=str(root),assignment=a,arm=arm,phase=phase,start=started)
    if phase=='preflight':
        # One source root per outcome stratum, both algorithms; every search repeated.
        selected=[next(r for r in assignments if r['group']==g) for g in ('fatal','surviving')]
        jobs=[job(a,arm) for a in selected for arm in ARMS]
        reports=[worker(j) for j in jobs]
    else:
        E.require(E.read(root/'preflight/result.json')['status']=='complete','P205 preflight incomplete')
        jobs=[job(a,arm) for a in assignments for arm in ('control',*ARMS)];reports=[]
        with ProcessPoolExecutor(max_workers=DESIGN['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
            futures={pool.submit(worker,j):j for j in jobs}
            for future in as_completed(futures):
                j=futures[future]
                try: report=future.result()
                except Exception:
                    destination=folder/j['arm']/str(j['assignment']['reference']['seed'])
                    progress=E.read(destination/'status.json') if (destination/'status.json').exists() else {}
                    report={**progress,'status':'fault','arm':j['arm'],'seed':j['assignment']['reference']['seed'],
                            'group':j['assignment']['group'],'error':traceback.format_exc(),'process_failure':True}
                    M.put(destination/'result.json',report)
                reports.append(report)
                progress=dict(status='P205_'+phase,complete=len(reports),assigned=len(jobs),faults=sum(r['status']=='fault' for r in reports),seconds=time.monotonic()-started)
                M.put(root/'status.json',progress)
                print(progress,flush=True)
    faults=[r for r in reports if r['status']=='fault']
    result=dict(status='incomplete_faults' if faults else 'complete',phase=phase,assigned=len(jobs),faults=faults,
        search_calls=sum(r.get('search_calls',0) for r in reports),control_calls=sum(r.get('controls',0) for r in reports),
        suffix_calls=sum(r.get('suffix_calls',0) for r in reports),full_replans=sum(r.get('full_replans',0) for r in reports),
        recorded_rollouts=sum(r.get('rollouts',r.get('recorded_rollouts',0)) for r in reports),
        transitions=sum(r.get('transitions',0) for r in reports),updates=sum(r.get('updates',0) for r in reports),
        seconds=time.monotonic()-started,policy_adoption=False,unseen_acceptance_games=0)
    if not faults:
        result['arms']={arm:{group:dict(assigned=sum(r['arm']==arm and r['group']==group for r in reports),
            survived=sum(r.get('survived',False) for r in reports if r['arm']==arm and r['group']==group),
            heart=sum(bool(r.get('heart')) for r in reports if r['arm']==arm and r['group']==group))
            for group in ('fatal','surviving')} for arm in ARMS}
        if phase=='main':
            a=result['arms']['adaptive']['fatal']['survived'];b=result['arms']['sampling']['fatal']['survived']
            result['mechanism_gate_passed']=a>=4 and a-b>=3
    M.put(folder/'result.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','preflight','main'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--runtime',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.runtime.resolve())
    else:execute(root,args.command)
