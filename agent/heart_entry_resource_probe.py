"""P206: finite reachability and an explicitly artificial HP intervention."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
import multiprocessing
from pathlib import Path
import time
import traceback

import heart_adaptive_rollout_probe as P
import heart_prefix_reachability as Q

A,M,E,D=P.A,P.M,P.E,P.D
RECIPE=dict(target_turn=3,node_limit=300000,depth_limit=96,seconds_per_tree=180,
            workers=8,stage_seconds=3600,maximum_counterfactual_resolutions=24,
            maximum_prefix_searches=48,preflight_nodes=128)


def prepare(root, source, recovery=None):
    root.mkdir(parents=True)
    evidence=E.read(source/'main/artifact-review.json')
    E.require(evidence['status']=='passed' and evidence['unresolved_faults']==0,'P205 source not verified')
    assignments=E.read(source/'assignments-private.json')
    M.put(root/'assignments-private.json',assignments)
    bound=[Path(__file__),Path(Q.__file__),Path(P.__file__),Path(A.__file__),Path(M.__file__),
           source/'protocol.json',source/'main/result.json',source/'main/artifact-review.json',
           source/'assignments-private.json',root/'assignments-private.json']
    for a in assignments:
        seed=str(a['reference']['seed'])
        bound.extend([Path(a['reference']['path']),source/'main/control'/seed/'attempt.json'])
        for arm in ('sampling','adaptive'):
            bound.append(source/'main'/arm/seed/'search-1.json.gz')
    if recovery is not None:
        E.require(E.read(recovery/'native-record-contract-review.json')['status']=='passed',
                  'recovery native records have not been verified')
        E.require(E.sha(recovery/'assignments-private.json')==E.sha(root/'assignments-private.json'),
                  'recovery assignment differs')
        bound.extend([recovery/'protocol.json',recovery/'main/result.json',
                      recovery/'native-record-contract-review.json',recovery/'repair-registration.json'])
        bound.extend(recovery/'main'/str(a['reference']['seed'])/'counterfactual-attempt.json' for a in assignments)
    plan=dict(experiment='P206',source=str(source),recipe=RECIPE,
        hashes={str(p):E.sha(p) for p in bound},
        question='Separate solver non-discovery from a finite-horizon impossibility certificate, and measure whether entry HP alone is sufficient to change combat outcome under the fixed native MCTS.',
        population='Exactly the24 P205 roots:16 historical-fit terminal fatal battles and8 original Heart wins. No new families. Outcome-enriched diagnostic; not a natural win-rate cohort.',
        natural='Restore exact native root from its natural prefix. Reuse verified original MCTS, sampling and adaptive paths as possible finite-horizon witnesses. Otherwise enumerate all native legal actions to turn3 or alive victory/escape.',
        artificial='On a separate prefix-restored GameContext set only cur_hp=max_hp before BattleContext.init. Reverting that one field must reproduce the original full game fingerprint. Keep maximum HP, deck, relics, potions and game RNG fixed. Low-HP relic effects caused by initialization are intended consequences. This is not a legally reached state and never counts as a natural run or deployable policy.',
        counterfactual_planner='Original native MCTS8000/boss3 once on each changed-HP state. When HP was full, reuse its identical verified original plan, not another planning call. Replay every returned plan with native legality and exact post-battle game fingerprint.',
        enumerator='Depth-first action-bit order; all menus from the frozen native get_legal_actions. No heuristic pruning or transposition merging. Stop at a legal alive prefix at native turn>=3, or alive battle victory/escape. Complete terminal losses are dead. Enumerate remaining branches for a negative certificate. Node,depth or time limits produce unknown, never death.',
        horizon='Native turn starts at0 in these roots. turn>=3 while alive is a necessary, not sufficient, prefix condition for battles that continue through three turn increments. It is not proof of complete battle survival.',
        verification='Native source replay and root signatures; independent re-enumeration of every recorded certificate menu/edge. Missing branches, death on the target turn, and cycles under a depth cap cannot pass as survival or impossibility.',
        interpretation='Report all24 paired native outcomes, fatal versus surviving strata, and exact-prefix feasible/closed-dead/unknown separately. A rescued full-HP counterfactual only establishes sufficiency of this artificial resource intervention under this solver; it does not prove a legal earlier healing choice exists or identify a neural policy.',
        stopping='One horizon and one HP intervention; no horizon/node/HP/solver-budget sweep. If certificates are unknown, retain unknown. Positive diagnostics require tracing a legal earlier decision before any policy proposal.',
        policy_adoption=False,new_natural_games=0,unseen_acceptance_games=0)
    if recovery is not None:
        plan['recovery']=str(recovery)
        plan['recovery_scope']='Reuse the exact24 saved counterfactual plans after native full-state verification. Fix only replay-contract interpretation: native is_valid accepts equivalent recorded encodings and native reported turns are turn index+1. No new MCTS calls; unchanged HP intervention and exhaustive-prefix recipe.'
    M.put(root/'protocol.json',plan)
    print(dict(status='P206_prepared',assigned=len(assignments),recipe=RECIPE),flush=True)


@lru_cache(maxsize=1)
def checked(root):
    plan=E.read(root/'protocol.json')
    E.require(plan['recipe']==RECIPE,'P206 recipe changed')
    for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'P206 bound input changed: '+path)
    P.checked(Path(plan['source']))
    return plan


def known_prefix(adapter,battle,candidates,target):
    for name,actions in candidates:
        found=Q.trace(adapter,battle,actions,target)
        if found is not None:
            return dict(verdict='surviving_prefix',method='existing_native_witness',source=name,
                        target_turn=target,actions=found['actions'],terminal_signature=A.signature(found['state']))
    return None


def replay_counterfactual(x, seed, prefix, maximum, battle, record, source):
    """Follow the frozen runtime's native replay contract, then check the GC."""
    adapter=Q.Native(x.R.sts);final=battle.clone()
    for bits in record['actions']:
        adapter.execute(final,bits)  # Native is_valid handles signed/alias records.
    E.require(int(final.outcome)==record['outcome'] and int(final.turn)+1==record['turns'],
              'native recorded outcome/turn count differs')
    replay_gc=x.R.replay(seed,prefix,x.config);replay_gc.cur_hp=maximum
    final.exit_battle(replay_gc);x.R.clock_input(replay_gc,x.config)
    expected=record.get('terminal_fingerprint',source['terminal_fingerprint'])
    E.require(x.R.fingerprint(replay_gc)==expected,'counterfactual terminal game differs')
    return final,expected


def worker(job):
    root=Path(job['root']);assignment=job['assignment'];seed=assignment['reference']['seed']
    folder=root/'main'/str(seed);folder.mkdir(parents=True)
    started=time.monotonic();new_resolutions=0;new_simulations=0;searches=0;nodes=0;actions=0
    try:
        plan=checked(root);source_root=Path(plan['source'])
        E.require(time.monotonic()-job['start']<RECIPE['stage_seconds'],'P206 stage deadline')
        x,source,prefix,gc,natural=P.state(source_root,assignment)
        adapter=Q.Native(x.R.sts);natural_signature=A.signature(natural)
        original_fingerprint=x.R.fingerprint(gc);original_hp=int(gc.cur_hp);maximum=int(gc.max_hp)
        original=assignment['root_control']
        counter_gc=x.R.replay(seed,prefix,x.config)
        counter_gc.cur_hp=maximum
        counter_fingerprint=x.R.fingerprint(counter_gc)
        counter_gc.cur_hp=original_hp
        E.require(x.R.fingerprint(counter_gc)==original_fingerprint,'HP intervention changed other game fields')
        counter_gc.cur_hp=maximum
        full=x.R.sts.BattleContext();full.init(counter_gc)
        if original_hp==maximum:
            E.require(A.signature(full)==natural_signature and counter_fingerprint==original_fingerprint,
                      'full-HP control differs')
        if 'recovery' in plan:
            counter=E.read(Path(plan['recovery'])/'main'/str(seed)/'counterfactual-attempt.json')
        elif original_hp==maximum:
            counter=dict(original)
        else:
            new_resolutions+=1
            M.put(folder/'status.json',dict(status='native_counterfactual',new_resolutions=new_resolutions))
            counter=dict(x.R.sts.resolve_battle_recorded(counter_gc,x.config['simulations'],x.config['boss_multiplier']))
            new_simulations+=counter['simulations']
            x.R.clock_input(counter_gc,x.config)
            counter['terminal_fingerprint']=x.R.fingerprint(counter_gc)
        M.put(folder/'counterfactual-attempt.json',counter)
        # Both kinds of returned plans are replayed from their correct state.
        final,expected=replay_counterfactual(x,seed,prefix,maximum,full,counter,source)
        M.put(folder/'counterfactual-result.json',dict(initial_hp=original_hp,intervened_hp=maximum,
            root_fingerprint=counter_fingerprint,terminal_fingerprint=expected,
            root_signature=A.signature(full),terminal_signature=A.signature(final),
            reused_full_hp_control=original_hp==maximum,alive=adapter.terminal(final)[1],
            new_planning_calls=new_resolutions,new_simulations=new_simulations,
            legal_natural_route=original_hp==maximum,new_natural_game=False))
        candidates=[('original_mcts',original['actions'])]
        for arm in ('sampling','adaptive'):
            prior=E.read(source_root/'main'/arm/str(seed)/'search-1.json.gz')
            candidates.append(('P205_'+arm,prior['actions']))
        variants={}
        for name,battle,paths in [('natural',natural,candidates),('full_hp',full,[('counterfactual_mcts',counter['actions'])])]:
            before=A.signature(battle)
            verdict=known_prefix(adapter,battle,paths,RECIPE['target_turn'])
            if verdict is None:
                searches+=1
                def progress(values):M.put(folder/(name+'-progress.json'),dict(status='enumerating',**values))
                M.put(folder/'status.json',dict(status='enumerating',variant=name,new_resolutions=new_resolutions,
                                               prefix_searches=searches))
                tree,ending=Q.search(adapter,battle,RECIPE['target_turn'],RECIPE['node_limit'],RECIPE['depth_limit'],
                                    RECIPE['seconds_per_tree'],progress=progress)
                nodes+=len(tree['nodes']);actions+=tree['actions_executed']
                M.put(folder/(name+'-tree.json.gz'),tree)
                audit=Q.verify(adapter,battle,tree)
                verdict={k:v for k,v in tree.items() if k!='nodes'}
                verdict.update(method='native_exhaustive_prefix',nodes=len(tree['nodes']),audit=audit,
                               terminal_signature=A.signature(ending) if ending is not None else None)
            E.require(A.signature(battle)==before and A.signature(natural)==natural_signature
                      and x.R.fingerprint(gc)==original_fingerprint,'P206 mutated a root')
            verdict['root_signature']=before
            M.put(folder/(name+'-prefix.json'),verdict)
            variants[name]={k:verdict[k] for k in ('verdict','method')}
        report=dict(status='complete',seed=seed,group=assignment['group'],initial_hp=original_hp,max_hp=maximum,
            original_survived=assignment['group']=='surviving',full_hp_survived=adapter.terminal(final)[1],
            variants=variants,new_resolutions=new_resolutions,new_simulations=new_simulations,
            prefix_searches=searches,nodes=nodes,actions=actions,seconds=time.monotonic()-started)
    except Exception:
        progress={p.name:E.read(p) for p in folder.glob('*-progress.json')}
        report=dict(status='fault',seed=seed,group=assignment['group'],error=traceback.format_exc(),
            new_resolutions=new_resolutions,new_simulations=new_simulations,prefix_searches=searches,
            completed_nodes=nodes,completed_actions=actions,progress=progress,seconds=time.monotonic()-started,
            note='A fault is unresolved and not a battle death or a closed reachability tree.')
    M.put(folder/'result.json',report);return report


def preflight(root):
    plan=checked(root);assignment=E.read(root/'assignments-private.json')[0]
    x,source,prefix,gc,battle=P.state(Path(plan['source']),assignment)
    adapter=Q.Native(x.R.sts);before=A.signature(battle)
    tree,_=Q.search(adapter,battle,RECIPE['target_turn'],RECIPE['preflight_nodes'],RECIPE['depth_limit'],30)
    M.put(root/'preflight/tree.json.gz',tree)
    audit=Q.verify(adapter,battle,tree)
    E.require(A.signature(battle)==before,'preflight changed root')
    # Existing source path gives an independent positive finite-horizon witness.
    witness=Q.trace(adapter,battle,assignment['root_control']['actions'],RECIPE['target_turn'])
    E.require(witness is not None,'preselected original path does not reach horizon')
    original_hp=int(gc.cur_hp)
    gc.cur_hp=int(gc.max_hp);gc.cur_hp=original_hp
    E.require(x.R.fingerprint(gc)==assignment['before'],'single HP field restore differs')
    result=dict(status='passed',seed=source['seed'],nodes=len(tree['nodes']),actions=tree['actions_executed'],
        verdict=tree['verdict'],native_tree_review=audit,positive_witness_actions=len(witness['actions']),
        new_resolutions=0,new_natural_games=0)
    if 'recovery' in plan:
        counts=[]
        for item in E.read(root/'assignments-private.json'):
            xx,original,pre,context,_=P.state(Path(plan['source']),item)
            context.cur_hp=int(context.max_hp)
            live=xx.R.sts.BattleContext();live.init(context)
            raw=E.read(Path(plan['recovery'])/'main'/str(item['reference']['seed'])/'counterfactual-attempt.json')
            replay_counterfactual(xx,original['seed'],pre,int(context.max_hp),live,raw,original)
            counts.append(len(raw['actions']))
        result['recovery_plans_replayed']=len(counts)
        result['recovery_actions_replayed']=sum(counts)
    M.put(root/'preflight/result.json',result);print(result,flush=True)


def execute(root):
    checked(root);E.require(E.read(root/'preflight/result.json')['status']=='passed','preflight required')
    started=time.monotonic();assignments=E.read(root/'assignments-private.json');(root/'main').mkdir();reports=[]
    jobs=[dict(root=str(root),assignment=a,start=started) for a in assignments]
    with ProcessPoolExecutor(max_workers=RECIPE['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
        futures={pool.submit(worker,j):j for j in jobs}
        for future in as_completed(futures):
            job=futures[future]
            try:report=future.result()
            except Exception:
                report=dict(status='fault',seed=job['assignment']['reference']['seed'],
                            group=job['assignment']['group'],error=traceback.format_exc(),process_failure=True)
                M.put(root/'main'/str(report['seed'])/'result.json',report)
            reports.append(report)
            progress=dict(status='P206_running',complete=len(reports),assigned=len(jobs),
                          faults=sum(r['status']=='fault' for r in reports),seconds=time.monotonic()-started)
            M.put(root/'status.json',progress);print(progress,flush=True)
    faults=[r for r in reports if r['status']=='fault']
    result=dict(status='incomplete_faults' if faults else 'complete',assigned=len(assignments),faults=faults,
                seconds=time.monotonic()-started,policy_adoption=False,new_natural_games=0,unseen_acceptance_games=0)
    result['costs']={k:sum(r.get(k,0) for r in reports) for k in
                     ('new_resolutions','new_simulations','prefix_searches','nodes','actions')}
    if not faults:
        result['strata']={}
        for group in ('fatal','surviving'):
            rows=[r for r in reports if r['group']==group]
            result['strata'][group]=dict(assigned=len(rows),original_survived=sum(r['original_survived'] for r in rows),
                full_hp_survived=sum(r['full_hp_survived'] for r in rows),
                already_full_hp=sum(r['initial_hp']==r['max_hp'] for r in rows),
                prefixes={variant:dict(Counter(r['variants'][variant]['verdict'] for r in rows))
                          for variant in ('natural','full_hp')})
    M.put(root/'main/result.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','preflight','run'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--source',type=Path)
    parser.add_argument('--recovery',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.source.resolve(),args.recovery.resolve() if args.recovery else None)
    elif args.command=='preflight':preflight(root)
    else:execute(root)
