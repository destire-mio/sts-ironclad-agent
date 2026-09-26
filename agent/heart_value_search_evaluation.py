"""P210 frozen learned-value search: native tactical and natural-game tests."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from functools import lru_cache
import importlib
import math
import multiprocessing
from pathlib import Path
import sys
import time
import traceback

import numpy as np
import heart_combat_value_data as C

E,M,D=C.E,C.M,C.D
ARMS=('learned','constant')
DESIGN=dict(workers=4,seconds=14400,episode_seconds=1800,simulations=8000,boss_multiplier=3,
    tactical_families=24,whole_families=128,minimum_net_gain=8,paired_p_limit=.025)


def prepare(root):
    plan=C.checked(root);fit=E.read(root/'fit/result.json');E.require(fit['status']=='complete','fitted model required')
    destination=root/'search';E.require(not (destination/'protocol.json').exists(),'execution already frozen')
    original=Path(E.read(Path('runs/p201-temporal-credit-20260924-01/protocol.json'))['source'])
    role_path=original/'roles-private.json';seeds=E.read(role_path)['evaluation']
    refs=E.read(Path(plan['runtime']).parent/'fit-references.json');by_seed={r['seed']:r for r in refs}
    evaluation=[by_seed[s] for s in seeds];E.require(len(evaluation)==len(set(seeds))==128,'evaluation denominator')
    tactical_path=Path('runs/p205-adaptive-battle-search-20260924-02/assignments-private.json').resolve()
    tactical=E.read(tactical_path);training=E.read(root/'assignments-private.json')
    E.require(not set(seeds)&{a['reference']['seed'] for a in training},'fit/evaluation overlap')
    E.require(not {a['reference']['seed'] for a in tactical}&{a['reference']['seed'] for a in training},'fit/tactical overlap')
    E.require(sum(r['status']=='heart_win' for r in evaluation)==20,'parent denominator changed')
    M.put(destination/'evaluation-private.json',evaluation)
    paths=[Path(__file__),Path(__file__).with_name('heart_value_search.cpp'),Path(__file__).with_name('heart_combat_features.h'),
        Path(__file__).with_name('heart_combat_value_data.py'),Path(__file__).with_name('heart_combat_value_fit.py'),
        destination/'heart_value_search.cpython-312-darwin.so',destination/'build-command.json',destination/'evaluation-private.json',
        root/'fit/model.npz',root/'fit/model.pt',root/'fit/result.json',root/'fit/protocol.json',root/'protocol.json',root/'result.json',
        role_path,tactical_path,Path(M.__file__),Path(D.__file__),Path(E.__file__)]
    recipe=dict(experiment='P210',phase='execution',runtime=plan['runtime'],design=DESIGN,
        hashes={str(p.resolve()):E.sha(p) for p in paths},tactical_path=str(tactical_path),
        learned='At each new tree node enumerate all original legal actions. Execute each on a clone; predict child quality from the frozen public encoder and fitted64-64 sigmoid model. True terminal children use exact normalized native value. Softmax temperature.2 mixed with.1 uniform gives positive priors. PUCT adds original4.242640687119286 exploration constant times prior*sqrt(parentVisits+1)/(childVisits+1) to original normalized maximum terminal return. Leaf first actions sample these priors. Full native random terminal rollout, max-backup and8000/boss3 per-replan budget remain.',
        constant='Exactly the same algorithm, terminal child values and budgets, with.5 for every nonterminal child. This control separates learned state discrimination from changing UCB to PUCT; its terminal-child prior is not uniform.',
        execution='Native15-step cached winning plan /5-step most-visited fallback;256 replans and500 battle turns. Original outside parent. Real full simulated terminals alone establish outcomes. No root search predictions are declared wins.',
        preflight='Check C++ predictions against exported NumPy at20 witnessed states. At2 first fitting roots, two64-simulation cold searches per arm and a zero-weight learned vs constant equivalence pair. Replay all returned plans. Two stock companion battles must equal their source records; two full stock natural evaluation games must equal source trajectories. Preflight does not choose a model.',
        evaluation='Complete24 tactical roots for both arms with original-state legal replay, then128 historical E191 development families for both complete natural policies regardless of tactical rescue count. Every full-game winner replanned from natural start with cold model load. Parent references replayed, outside choices recomputed. No dropped faults. No checkpoint or recipe selection using individual roots.',
        adoption='Candidate must have net>=8/128 and paired two-sided binomial p<.025 versus original parent with zero unresolved faults; report learned-versus-constant effect separately. These repeatedly used historical development families cannot establish unseen acceptance. Qualifying candidate requires prospective validation before final1024.',
        time_limit='1800seconds per natural game for both arms;800 steps and original per-search simulation budgets. The larger wall limit permits extra neural computation, not extra simulations. Record wall time and extra child-state transitions as costs.',
        limits=dict(tactical_resolvers=48,whole_games=256,whole_winner_replans_max=256,stock_natural_controls=2,
                    preflight_profiles=12,preflight_simulations=768,stock_battle_controls=2),
        policy_adoption=False,unseen_acceptance_games=0)
    M.put(destination/'protocol.json',recipe);print(dict(status='execution_frozen',whole_games=256,tactical_resolvers=48),flush=True)


@lru_cache(maxsize=1)
def checked(root):
    C.checked(root);plan=E.read(root/'search/protocol.json');E.require(plan['design']==DESIGN,'execution recipe changed')
    for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'execution source changed: '+path)
    return plan


def load(root):
    plan=checked(root);x=D.runtime(plan['runtime']);sys.path.insert(0,str(root/'search'))
    module=importlib.import_module('heart_value_search');data=np.load(root/'fit/model.npz')
    model=module.ValueNetwork(*(data[k] for k in ('w1','b1','w2','b2','w3','b3')))
    return plan,x,module,model


def replay_battle(x,battle,result):
    b=battle.clone()
    for bits in result['actions']:
        action=x.R.sts.SearchAction.from_bits(bits&0xffffffff);E.require(action.is_valid(b),'illegal searched action');action.execute(b)
    E.require(b.outcome!=x.R.sts.Outcome.UNDECIDED,'nonterminal searched path')
    if 'outcome' in result:E.require(int(b.outcome)==result['outcome'] and b.turn+1==result['turns'],'battle result differs')
    return b


def public_numpy(root,features,width):
    data=np.load(root/'fit/model.npz');v=np.zeros(width,dtype=np.float32)
    for i,value in features:v[i]=value
    v=np.maximum(0,data['w1']@v+data['b1']);v=np.maximum(0,data['w2']@v+data['b2'])
    return float((1/(1+np.exp(-(data['w3']@v+data['b3']))))[0])


def stock_reference(x,reference,recompute_outside=True):
    E.require(E.sha(reference['path'])==reference['sha256'],'parent reference changed')
    run=E.read(reference['path']);E.require(run['checkpoint_sha256']==x.identity['model_sha256'] and run['engine_sha256']==x.identity['engine_sha256'],'parent identity differs')
    audit=M.check_route(x,run);count=0
    if recompute_outside:
        parent=E.parent_model(x);gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,reference['seed'],20)
        for step in run['prefix']:
            x.R.clock_input(gc,x.config)
            if step['kind']=='outside':
                actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc)
                chosen=parent.choose(gc,x.A.obs_vec(gc),actions,ds)
                E.require(int(actions[chosen].bits)==step['action'],'parent outside choice changed');count+=1
            x.R.replay_step(gc,step,x.config)
    return run,dict(**audit,outside_recomputed=count)


def preflight(root):
    plan,x,module,model=load(root);_,_,encoder=C.load(root)
    assignments=E.read(root/'assignments-private.json')[:2];folder=root/'search/preflight';folder.mkdir()
    exported=np.load(root/'fit/model.npz');zero=module.ValueNetwork(*(np.zeros_like(exported[k]) for k in ('w1','b1','w2','b2','w3','b3')))
    reports=[];profiles=0;simulations=0;native_transitions=0;prediction_errors=[]
    for assignment in assignments:
        seed=assignment['reference']['seed'];location=assignment['roots'][0];battle=C.state(x,assignment,location);signature=C.P.A.signature(battle)
        data=E.read(root/'collection'/str(seed)/f"{location['index']}-attempt.json.gz")
        for row in data['rows'][:10]:
            state=battle.clone()
            for bits in row['path']:
                action=x.R.sts.SearchAction.from_bits(bits&0xffffffff);E.require(action.is_valid(state),'invalid inference witness');action.execute(state);native_transitions+=1
            width,features=encoder.features(state);prediction_errors.append(abs(model.predict(state)-public_numpy(root,features,width)))
        for arm in ARMS:
            results=[]
            for repeat in range(2):
                result=dict(module.profile(battle,64,model,arm));profiles+=1;simulations+=result['cost']['simulations']
                M.put(folder/f'{seed}-{arm}-{repeat}.json',result);ending=replay_battle(x,battle,result);native_transitions+=len(result['actions'])
                E.require(encoder.terminal_value(ending)==result['native_value'] and ending.player.cur_hp==result['hp'],'profile value has no true terminal witness')
                results.append(result)
            E.require(all(results[0][k]==results[1][k] for k in ('actions','native_value','hp')),'cold search differs')
        a=dict(module.profile(battle,64,zero,'learned'));b=dict(module.profile(battle,64,zero,'constant'));profiles+=2
        simulations+=a['cost']['simulations']+b['cost']['simulations'];M.put(folder/f'{seed}-zero-control.json',dict(learned=a,constant=b))
        E.require(all(a[k]==b[k] for k in ('actions','native_value','hp')),'learned code changes search with constant predictions')
        native_transitions+=len(a['actions'])+len(b['actions']);replay_battle(x,battle,a);replay_battle(x,battle,b)
        E.require(signature==C.P.A.signature(battle),'profile mutated real root')
        original=E.read(assignment['reference']['path'])['prefix'][location['index']]
        clone=battle.clone();control=dict(module.resolve_state(clone,8000,3,model,'stock'));M.put(folder/f'{seed}-stock-battle.json',control)
        E.require(all(control[k]==original[k] for k in ('actions','simulations','turns','outcome')),'stock companion diverges from original native battle')
        ending=replay_battle(x,battle,control);E.require(C.P.A.signature(ending)==C.P.A.signature(clone),'stock battle full state differs')
        native_transitions+=len(control['actions']);simulations+=control['simulations'];reports.append(dict(seed=seed,stock_simulations=control['simulations']))
    E.require(max(prediction_errors)<2e-6,'C++ export inference mismatch')
    controls=[]
    for reference in E.read(root/'search/evaluation-private.json')[:2]:
        controls.append(whole_worker(dict(root=str(root),reference=reference,arm='stock',phase='controls')))
    E.require(all(r['status']=='complete' for r in controls),'stock natural controls failed')
    result=dict(status='passed',profiles=profiles,simulations=simulations+sum(r['simulations'] for r in controls),
        prediction_states=len(prediction_errors),prediction_max_error=max(prediction_errors),native_transitions=native_transitions,
        reports=reports,stock_natural_controls=controls,protocol_sha256=E.sha(root/'search/protocol.json'))
    M.put(root/'search/preflight.json',result);print({k:v for k,v in result.items() if k not in ('reports','stock_natural_controls')},flush=True)


def play(root,x,module,model,seed,arm,folder):
    folder.mkdir();original=x.R.sts.resolve_battle_recorded;ledger=[];calls=0
    def override(gc,simulations,boss_multiplier):
        nonlocal calls
        calls+=1;path=folder/f'battle-{calls:03d}.json'
        M.put(path,dict(status='planning',before=x.R.fingerprint(gc),arm=arm))
        result=dict(module.resolve_battle(gc,simulations,boss_multiplier,model,arm))
        M.put(path,dict(status='complete',arm=arm,**result));ledger.append(result['cost'])
        return {k:result[k] for k in ('actions','simulations','turns','outcome')}
    x.R.sts.resolve_battle_recorded=override
    try:
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
        run=x.R.rollout(seed,dict(x.config,episode_seconds=DESIGN['episode_seconds']),gc=gc,net=E.parent_model(x),record=True,record_samples=False)
        x.R.clock_input(gc,x.config)
        run.update(terminal_fingerprint=x.R.fingerprint(gc),engine_sha256=x.identity['engine_sha256'],
            checkpoint_sha256=x.identity['model_sha256'],combat_model_sha256=E.sha(root/'fit/model.npz'),combat_arm=arm)
        M.put(folder/'attempt.json.gz',run)
        run['audit']=M.check_route(x,run);M.put(folder/'run.json.gz',run)
        return run,ledger
    finally:x.R.sts.resolve_battle_recorded=original


def whole_worker(job):
    root=Path(job['root']);reference=job['reference'];seed=reference['seed'];arm=job['arm'];phase=job['phase']
    folder=root/'search'/phase/arm/str(seed);folder.mkdir(parents=True);started=time.monotonic();ledgers=[];attempts=0
    try:
        _,x,module,model=load(root);source,audit=stock_reference(x,reference)
        attempts+=1;run,ledger=play(root,x,module,model,seed,arm,folder/'first');ledgers+=ledger
        if arm=='stock':
            E.require(run['prefix']==source['prefix'] and run['terminal_fingerprint']==source['terminal_fingerprint'],'full stock planning changed source')
        elif run['status']=='heart_win':
            _,_,cold_module,cold_model=load(root);attempts+=1
            repeat,ledger=play(root,x,cold_module,cold_model,seed,arm,folder/'repeat');ledgers+=ledger
            E.require(repeat['prefix']==run['prefix'] and repeat['terminal_fingerprint']==run['terminal_fingerprint'],'complete Heart replan differs')
        result=dict(status='complete',seed=seed,arm=arm,parent_win=source['status']=='heart_win',
            heart=run['status']=='heart_win',ending=run['status'],act=run['act'],floor=run['floor'],hp=run['hp'],attempts=attempts,
            simulations=sum(c['simulations'] for c in ledgers),search_transitions=sum(c['search_transitions'] for c in ledgers),
            prior_transitions=sum(c['prior_transitions'] for c in ledgers),predictions=sum(c['predictions'] for c in ledgers),
            search_seconds=sum(c['search_seconds'] for c in ledgers),seconds=time.monotonic()-started,source_audit=audit)
    except Exception:
        paths=list(folder.glob('*/battle-*.json'));costs=[r['cost'] for p in paths if (r:=E.read(p)).get('status')=='complete']
        result=dict(status='fault',seed=seed,arm=arm,attempts=attempts,error=traceback.format_exc(),
            simulations=sum(c['simulations'] for c in costs),completed_battles=len(costs),unfinished_battles=len(paths)-len(costs),
            seconds=time.monotonic()-started,limits='Unreturned native work can be uncounted; a fault is not a death.')
    M.put(folder/'result.json',result);return result


def tactical_worker(job):
    root=Path(job['root']);assignment=job['assignment'];seed=assignment['reference']['seed'];arm=job['arm']
    folder=root/'search/tactical'/arm/str(seed);folder.mkdir(parents=True);started=time.monotonic();result=None
    try:
        _,x,module,model=load(root);reference=assignment['reference'];E.require(E.sha(reference['path'])==reference['sha256'],'tactical source changed')
        run=E.read(reference['path']);gc=x.R.replay(seed,run['prefix'][:assignment['index']],x.config);x.R.clock_input(gc,x.config)
        E.require(x.R.fingerprint(gc)==assignment['before'],'tactical root changed')
        root_battle=x.R.sts.BattleContext();root_battle.init(gc);b=root_battle.clone()
        result=dict(module.resolve_state(b,8000,3,model,arm));M.put(folder/'attempt.json',result)
        ending=replay_battle(x,root_battle,result);E.require(C.P.A.signature(ending)==C.P.A.signature(b),'tactical state/RNG differs')
        report=dict(status='complete',seed=seed,arm=arm,group=assignment['group'],survived=b.outcome!=x.R.sts.Outcome.PLAYER_LOSS,
            outcome=int(b.outcome),hp=b.player.cur_hp,simulations=result['simulations'],cost=result['cost'],seconds=time.monotonic()-started)
    except Exception:
        report=dict(status='fault',seed=seed,arm=arm,group=assignment['group'],simulations=result['simulations'] if result else 0,
            error=traceback.format_exc(),seconds=time.monotonic()-started)
    M.put(folder/'result.json',report);return report


def paired(a,b):
    positive=sum(x and not y for x,y in zip(a,b));negative=sum(y and not x for x,y in zip(a,b));n=positive+negative
    p=min(1.,2*sum(math.comb(n,j) for j in range(min(positive,negative)+1))/2**n) if n else 1.
    return dict(families=len(a),wins=sum(a),reference_wins=sum(b),positive=positive,negative=negative,net=positive-negative,p=p)


def execute(root,phase):
    plan=checked(root);pre=E.read(root/'search/preflight.json');E.require(pre['status']=='passed' and pre['protocol_sha256']==E.sha(root/'search/protocol.json'),'preflight incomplete')
    E.require(not (root/'search'/phase).exists(),'fresh phase required');started=time.monotonic();reports=[]
    if phase=='tactical':
        assignments=E.read(plan['tactical_path']);jobs=[dict(root=str(root),assignment=a,arm=arm) for a in assignments for arm in ARMS];worker=tactical_worker
    else:
        references=E.read(root/'search/evaluation-private.json');jobs=[dict(root=str(root),reference=r,arm=arm,phase='whole') for r in references for arm in ARMS];worker=whole_worker
    with ProcessPoolExecutor(max_workers=DESIGN['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
        futures={pool.submit(worker,j):j for j in jobs}
        for future in as_completed(futures):
            job=futures[future]
            try:report=future.result()
            except Exception:
                seed=(job['reference'] if phase=='whole' else job['assignment']['reference'])['seed']
                report=dict(status='fault',seed=seed,arm=job['arm'],simulations=0,error=traceback.format_exc(),process_failure=True)
                M.put(root/'search'/phase/job['arm']/str(seed)/'result.json',report)
            reports.append(report)
            progress=dict(status=phase,complete=len(reports),assigned=len(jobs),faults=sum(r['status']=='fault' for r in reports),seconds=time.monotonic()-started)
            M.put(root/'search/status.json',progress)
            if len(reports)%8==0:print(progress,flush=True)
            E.require(time.monotonic()-started<DESIGN['seconds'],'execution stage deadline')
    faults=[r for r in reports if r['status']=='fault']
    result=dict(status='complete' if not faults else 'incomplete_faults',phase=phase,assigned=len(jobs),faults=faults,
        simulations=sum(r['simulations'] for r in reports),seconds=time.monotonic()-started,policy_adoption=False,unseen_acceptance_games=0)
    if not faults and phase=='tactical':
        result['arms']={arm:{group:dict(assigned=sum(r['arm']==arm and r['group']==group for r in reports),
            survived=sum(r['survived'] for r in reports if r['arm']==arm and r['group']==group)) for group in ('fatal','surviving')} for arm in ARMS}
    elif not faults:
        table={(r['arm'],r['seed']):r for r in reports};seeds=[r['seed'] for r in references]
        parent=[r['status']=='heart_win' for r in references];values={arm:[table[arm,s]['heart'] for s in seeds] for arm in ARMS}
        result['arms']={arm:paired(values[arm],parent) for arm in ARMS};result['learned_vs_constant']=paired(values['learned'],values['constant'])
        result['adoption_gate']={arm:result['arms'][arm]['net']>=8 and result['arms'][arm]['p']<.025 for arm in ARMS}
        result['attempts']=sum(r['attempts'] for r in reports)
        result['cost_by_arm']={arm:{key:sum(r[key] for r in reports if r['arm']==arm) for key in ('simulations','search_transitions','prior_transitions','predictions','search_seconds','attempts')} for arm in ARMS}
    M.put(root/'search'/phase/'result.json',result);print({k:v for k,v in result.items() if k!='faults'},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','preflight','tactical','whole'));parser.add_argument('--root',required=True,type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root)
    elif args.command=='preflight':preflight(root)
    else:execute(root,args.command)
