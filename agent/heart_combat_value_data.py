"""P210: cross-family combat-value targets with native terminal witnesses."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import importlib
import multiprocessing
from pathlib import Path
import subprocess
import sys
import sysconfig
import time
import traceback

import heart_compositional_capability as M
import heart_adaptive_rollout_probe as P
import heart_future_return_probe as F

E,D=M.E,M.D
DESIGN=dict(fit_families=256,validation_families=64,roots_per_act=1,
    include_last_battle=True,maximum_roots_per_family=5,base_simulations=8000,boss_multiplier=3,
    minimum_visits=8,rows_per_root=128,workers=4,seconds=7200,
    model_hidden=[64,64],updates=4000,batch_families=64,learning_rate=.0003,weight_decay=.00001,
    gradient_norm=1.,training_seed=21020260924,prior_temperature=.2,uniform_prior_fraction=.1)


def prepare(root,runtime):
    E.require(not root.exists(),'fresh experiment directory required')
    roles_path=Path(E.read(Path('runs/p201-temporal-credit-20260924-01/protocol.json'))['source'])/'roles-private.json'
    excluded=set(E.read(roles_path)['evaluation'])
    diagnostic=Path('runs/p205-adaptive-battle-search-20260924-02').resolve()
    excluded.update(a['reference']['seed'] for a in E.read(diagnostic/'assignments-private.json'))
    refs=E.read(runtime.parent/'fit-references.json')
    refs=sorted((r for r in refs if r['seed'] not in excluded),key=lambda r:M.digest(['P210-family',r['seed']]))[:320]
    E.require(len(refs)==len({r['seed'] for r in refs})==320,'insufficient distinct families')
    x=D.runtime(str(runtime));assignments=[]
    for number,ref in enumerate(refs):
        E.require(E.sha(ref['path'])==ref['sha256'],'parent source changed')
        run=E.read(ref['path']);gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,ref['seed'],20);battles=[]
        for index,step in enumerate(run['prefix']):
            x.R.clock_input(gc,x.config)
            if step['kind']=='battle':
                E.require(x.R.fingerprint(gc)==step['before'],'natural battle root mismatch')
                battles.append(dict(index=index,before=step['before'],act=int(gc.act),floor=int(gc.floor_num),encounter=gc.encounter.name))
            x.R.replay_step(gc,step,x.config)
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
        E.require(battles,'family without combat')
        selected={battles[-1]['index']:battles[-1]}
        for act in sorted({b['act'] for b in battles}):
            chosen=min((b for b in battles if b['act']==act),key=lambda b:M.digest(['P210-root',ref['seed'],b['index']]))
            selected[chosen['index']]=chosen
        E.require(len(selected)<=5,'root budget exceeded')
        assignments.append(dict(reference=ref,role='fit' if number<256 else 'validation',roots=list(selected.values())))
    root.mkdir(parents=True);M.put(root/'assignments-private.json',assignments)
    provenance=F.PROVENANCE
    for name,digest in E.read(provenance/'portable-application.json')['source_files'].items():
        E.require(E.sha(provenance/'source'/name)==digest,'native source changed')
    E.require(E.sha(provenance/'build/slaythespire.cpython-312-darwin.so')==x.identity['engine_sha256'],'native library build differs')
    import pybind11
    cpp=Path(__file__).with_name('heart_combat_value.cpp');header=cpp.with_name('heart_combat_features.h')
    library=provenance/'build/libsts_core.a';binary=root/('heart_combat_value'+sysconfig.get_config_var('EXT_SUFFIX'))
    command=['/usr/bin/c++','-std=c++17','-O2','-UNDEBUG','-arch','arm64','-fPIC','-fvisibility=hidden',
        '-bundle','-undefined','dynamic_lookup','-flto','-I'+str(provenance/'source/include'),
        '-I'+pybind11.get_include(),'-I'+sysconfig.get_paths()['include'],str(cpp),str(library),'-o',str(binary)]
    with (root/'build.log').open('w') as output:subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,check=True)
    paths=[Path(__file__),cpp,header,binary,library,root/'assignments-private.json',runtime.parent/'fit-references.json',
           roles_path,diagnostic/'assignments-private.json',provenance/'portable-application.json']
    plan=dict(experiment='P210',phase='data',runtime=str(runtime),design=DESIGN,
        hashes={str(p.resolve()):E.sha(p) for p in paths},build_command=command,
        source='Original1536 fitting families, exclude128 E191 full-policy evaluation and24 P205 tactical diagnostic families. Outcome-blind hash selection256 fit+64 validation. One hashed battle per reached act plus last actual battle. Keep every assigned family and empty/terminal roots.',
        targets='At up to128 path-hash selected visited nodes per battle (at least8 visits), regress the best real terminal native E54 score found below that node, divided by100*(35+current maxHP+4*potionCapacity) and clipped0..1. A complete original-native legal path witnesses every label. This is a bounded-search optimistic target, not expected win probability, a proof of optimality or full Heart value. Undecided capped witnesses are excluded and counted, never labelled deaths.',
        features='Battle-only public inventory and visible player/enemy states, hand costs, special card amounts, relic counters and power order. Draw/discard/exhaust piles are aggregated by identity, upgrade and special amount. No seed/RNG/unique card IDs/hidden draw order; Runic Dome masks enemy intents. Current selection context and offered cards are included. Hidden enemy misc fields and future action outcomes are absent.',
        recorder='Use original native enumeration, UCB, RNG, rollout and maximum backup helpers, with an equivalent recording driver which saves each sampled terminal and the best witness pointer per tree node. Before collection compare best plan/value with original native search at2 fixed roots. All emitted node paths and full terminal witnesses replay using the frozen original native action executor; recompute public features and normalized labels.',
        learning='One64-64 ReLU network with sigmoid scalar output; family then root then node uniform sampling,4000 AdamW updates,lr3e-4,weight_decay1e-5,gradient clipping1,seed21020260924. No checkpoint/hyperparameter scan. Validation loss is diagnostic, not a win-rate gate.',
        search_integration='Learned child-state quality becomes a softmax prior at temperature.2 mixed with.1 uniform; PUCT uses original4.242640687119286 exploration constant and original normalized native maximum return. Constant-value PUCT is the matched algorithm control. Actual complete terminal rollouts, terminal scores and legal action execution remain native. Before deployment freeze inference export and full resolver under a separate execution protocol.',
        evaluation='After fitting freeze one model and run tactical P20524 roots plus both learned and constant-value PUCT from natural start on the128 E191 development families, with original parent outside policy and8000/boss3 budgets. Do not gate whole-policy comparison on terminal-failure root rescue alone: earlier resource changes may matter. Zero unresolved faults and every whole-game winner replanned. Adoption requires net>=8 and paired p<.025 versus original greedy parent; report learned-versus-constant effect and all computational cost. Final1024 untouched.',
        collection_limits=dict(families=320,roots=sum(len(a['roots']) for a in assignments),maximum_simulations=38400000,
                               maximum_rows=204800,preflight_searches=4,preflight_simulations=256),
        policy_adoption=False,unseen_acceptance_games=0)
    M.put(root/'protocol.json',plan);print(dict(status='prepared',families=320,roots=plan['collection_limits']['roots']),flush=True)


def checked(root):
    plan=E.read(root/'protocol.json');E.require(plan['design']==DESIGN,'P210 data recipe changed')
    for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'bound source changed: '+path)
    return plan


def load(root):
    plan=checked(root);x=D.runtime(plan['runtime']);sys.path.insert(0,str(root))
    return plan,x,importlib.import_module('heart_combat_value')


def state(x,assignment,root):
    ref=assignment['reference'];E.require(E.sha(ref['path'])==ref['sha256'],'natural parent changed')
    run=E.read(ref['path']);gc=x.R.replay(ref['seed'],run['prefix'][:root['index']],x.config);x.R.clock_input(gc,x.config)
    E.require(x.R.fingerprint(gc)==root['before'],'combat root state differs')
    battle=x.R.sts.BattleContext();battle.init(gc);return battle


def verify_rows(x,native,battle,data):
    transitions=0;rows=0
    for row in data['rows']:
        b=battle.clone();prefix=row['path'];full=row['terminal_path']
        E.require(full[:len(prefix)]==prefix,'terminal witness is not below labelled node')
        node=None
        for index in range(len(full)+1):
            if index==len(prefix):
                width,values=native.features(b);E.require(width==row['width'] and [list(v) for v in values]==[list(v) for v in row['features']],
                    'public features disagree with native witness node');node=b.clone()
            if index==len(full):break
            action=x.R.sts.SearchAction.from_bits(full[index]&0xffffffff)
            E.require(action.is_valid(b),'illegal terminal witness action');action.execute(b);transitions+=1
        value=native.terminal_value(b)
        E.require(int(b.outcome)==row['outcome'] and b.outcome!=x.R.sts.Outcome.UNDECIDED and b.player.cur_hp==row['terminal_hp'],
                  'terminal witness outcome mismatch')
        E.require(value==row['native_value'] and abs(native.quality(value,node)-row['target'])<1e-7,
                  'terminal witness target mismatch');rows+=1
    return dict(rows=rows,native_transitions=transitions)


def preflight(root):
    plan,x,native=load(root);assignments=E.read(root/'assignments-private.json');reports=[]
    original_path=Path('runs/p209-search-structure-20260924-01').resolve();sys.path.insert(0,str(original_path))
    original=importlib.import_module('heart_search_structure')
    for assignment in assignments[:2]:
        battle=state(x,assignment,assignment['roots'][0]);before=P.A.signature(battle)
        checks=dict(native.encoder_tests(battle));E.require(all(checks.values()),'public feature contract failed')
        data=dict(native.collect(battle,64,2,16));control=dict(original.profile(battle,64))
        M.put(root/'preflight'/f"{assignment['reference']['seed']}-attempt.json.gz",data)
        E.require(data['best_actions']==[int(a.bits) for a in control['best_actions']] and
                  data['best_value']==control['best_value'] and data['best_hp']==control['best_hp'],
                  'recording driver changed original search')
        verification=verify_rows(x,native,battle,data);E.require(before==P.A.signature(battle),'collector mutated root')
        reports.append(dict(seed=assignment['reference']['seed'],checks=checks,verification=verification,simulations=data['simulations']+control['simulations']))
    result=dict(status='passed',reports=reports,searches=4,simulations=sum(r['simulations'] for r in reports),protocol_sha256=E.sha(root/'protocol.json'))
    M.put(root/'preflight.json',result);print(result,flush=True)


def family(job):
    root=Path(job['root']);assignment=job['assignment'];seed=assignment['reference']['seed'];folder=root/'collection'/str(seed)
    folder.mkdir(parents=True);started=time.monotonic();simulations=0;calls=0;rows=0;transitions=0;reports=[]
    try:
        _,x,native=load(root)
        for location in assignment['roots']:
            battle=state(x,assignment,location);before=P.A.signature(battle)
            budget=8000*(3 if battle.encounter.name in P.A.BOSSES else 1);calls+=1
            data=dict(native.collect(battle,budget,8,128));simulations+=data['simulations']
            M.put(folder/f"{location['index']}-attempt.json.gz",data)
            E.require(before==P.A.signature(battle),'data collection mutated root')
            verification=verify_rows(x,native,battle,data);rows+=verification['rows'];transitions+=verification['native_transitions']
            reports.append(dict(index=location['index'],simulations=data['simulations'],rows=verification['rows'],
                eligible_nodes=data['eligible_nodes'],unknown_nodes=data['unknown_nodes'],
                search_transitions=data['search_transitions'],tree_replay_transitions=data['tree_replay_transitions'],verification=verification))
        result=dict(status='complete',seed=seed,role=assignment['role'],searches=calls,simulations=simulations,
                    rows=rows,verification_transitions=transitions,roots=reports,seconds=time.monotonic()-started)
    except Exception:
        result=dict(status='fault',seed=seed,role=assignment['role'],searches=calls,simulations=simulations,
                    rows=rows,roots=reports,error=traceback.format_exc(),seconds=time.monotonic()-started)
    M.put(folder/'result.json',result);return result


def collect_all(root):
    plan=checked(root);pre=E.read(root/'preflight.json')
    E.require(pre['status']=='passed' and pre['protocol_sha256']==E.sha(root/'protocol.json'),'preflight required')
    assignments=E.read(root/'assignments-private.json');rows=[];started=time.monotonic()
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
        futures=[pool.submit(family,dict(root=str(root),assignment=a)) for a in assignments]
        for future in as_completed(futures):
            rows.append(future.result());status=dict(status='collecting',complete=len(rows),assigned=320,
                faults=sum(r['status']=='fault' for r in rows),seconds=time.monotonic()-started)
            M.put(root/'status.json',status)
            if len(rows)%16==0:print(status,flush=True)
            E.require(time.monotonic()-started<DESIGN['seconds'],'data stage deadline')
    faults=[r for r in rows if r['status']=='fault']
    result=dict(status='complete' if not faults else 'incomplete_faults',families=320,searches=4+sum(r['searches'] for r in rows),
        simulations=pre['simulations']+sum(r['simulations'] for r in rows),rows=sum(r['rows'] for r in rows),faults=faults,
        roles={role:dict(families=sum(r['role']==role for r in rows),rows=sum(r['rows'] for r in rows if r['role']==role)) for role in ('fit','validation')},
        seconds=time.monotonic()-started,policy_adoption=False,unseen_acceptance_games=0)
    M.put(root/'result.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','preflight','collect'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--runtime',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.runtime.resolve())
    elif args.command=='preflight':preflight(root)
    else:collect_all(root)
