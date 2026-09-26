"""P208: paired future-combat sensitivity and independent-future action choice.

Synthetic conditional diagnostics, never natural-run wins or deployment.
The original game and search library stays byte-identical. The companion
resamples four battle-start streams while preserving the search RNG seed.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
import importlib
import multiprocessing
from pathlib import Path
import subprocess
import sys
import sysconfig
import time
import traceback

import heart_compositional_capability as M
import heart_adaptive_rollouts as B

E,D = M.E,M.D
DESIGN = dict(per_stratum=8, strata=[1,-1,0], discovery_worlds=8,
              confirmation_worlds=8, workers=8, seconds=5400,
              rollout_seconds=300, repeat_pairs=6)
PROVENANCE = Path('/Users/destire/Documents/ChatGPT/sljt/ironclad-alignment/evidence/e121-power-order-repair-20260920-01')


def order(*parts):
    return M.digest(['P208',*parts])


def prepare(root,source):
    E.require(not root.exists(),'fresh experiment directory required')
    rows=E.read(source/'fitting-rows.json')
    review=E.read(source/'artifact-review.json')
    E.require(review['unresolved_faults']==0 and len(rows)==701,'unverified source')
    references={r['seed']:r for r in E.read(source/'roles-private.json')['fit']}
    selected=[];used=set()
    for delta in DESIGN['strata']:
        eligible=sorted((r for r in rows if r['delta']==delta),
                        key=lambda r:order('pair',r['seed'],r['index'],r['action']))
        group=[]
        for row in eligible:
            if row['seed'] in used:continue
            used.add(row['seed']);group.append(row)
            if len(group)==DESIGN['per_stratum']:break
        E.require(len(group)==DESIGN['per_stratum'],'insufficient distinct source families')
        for row in group:
            reference=references[row['seed']]
            E.require(E.sha(reference['path'])==reference['sha256'],'parent source changed')
            record=E.read(row['record']);natural=E.read(reference['path'])
            E.require(len(record['changes'])==1 and record['changes'][0]['index']==row['index'],
                      'source contains additional interventions')
            E.require(record['run']['prefix'][:row['index']]==natural['prefix'][:row['index']],
                      'source parent prefix differs')
            E.require(int(record['run']['status']=='heart_win')-int(natural['status']=='heart_win')==delta,
                      'wrong original gain')
            selected.append(dict(row=row,reference=reference,record_sha256=E.sha(row['record']),
                parent_action=natural['prefix'][row['index']]['action'],
                before=natural['prefix'][row['index']]['before'],
                worlds=[int(order('world',row['seed'],i)[:15],16) for i in range(16)]))
    root.mkdir(parents=True)
    M.put(root/'assignments-private.json',selected)
    manifest=E.read(PROVENANCE/'portable-application.json')['source_files']
    for name,digest in manifest.items():
        E.require(E.sha(PROVENANCE/'source'/name)==digest,'frozen source changed: '+name)
    runtime=Path(E.read(source/'protocol.json')['runtime'])
    x=D.runtime(str(runtime))
    library=PROVENANCE/'build/libsts_core.a'
    E.require(E.sha(PROVENANCE/'build/slaythespire.cpython-312-darwin.so')==x.identity['engine_sha256'],
              'native build does not match frozen engine')
    import pybind11
    cpp=Path(__file__).with_name('heart_future_battles.cpp')
    binary=root/('heart_future_battles'+sysconfig.get_config_var('EXT_SUFFIX'))
    command=['/usr/bin/c++','-std=c++17','-O2','-UNDEBUG','-arch','arm64',
        '-fPIC','-fvisibility=hidden','-bundle','-undefined','dynamic_lookup','-flto',
        '-I'+str(PROVENANCE/'source/include'),'-I'+pybind11.get_include(),
        '-I'+sysconfig.get_paths()['include'],str(cpp),str(library),'-o',str(binary)]
    with (root/'build.log').open('w') as output:
        subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,check=True)
    bound=[Path(__file__),cpp,Path(M.__file__),Path(B.__file__),root/'assignments-private.json',
           source/'protocol.json',source/'artifact-review.json',source/'fitting-rows.json',
           PROVENANCE/'portable-application.json',library,binary]
    plan=dict(experiment='P208',source=str(source),runtime=str(runtime),design=DESIGN,
        binary=str(binary),build_command=command,hashes={str(p):E.sha(p) for p in bound},
        cohort='24 distinct original fitting families: 8 original positive, 8 negative and 8 zero rare-action pairs, chosen by hash within strata. Outcome-enriched diagnostic, not a population win-rate sample.',
        intervention='Only BattleContext initialization receives a temporary seed. Native ai/monsterHp/shuffle/cardRandom streams start from Random(worldSeed+floor). misc/potion streams, original GameContext seed, map, hidden pools and outside RNG stay as reached. Restore battle.seed before search, preserving original planner randomness. Subsequent consequences propagate. Same future seed for both actions and all fights in that pair/world.',
        limitation='These are synthetic sensitivity worlds, not samples from the exact posterior of naturally reachable seeds. Card/event/relic futures are not resampled except consequences of changed battles. No natural win or exact POMCP claim.',
        comparison='Original one-future selector chooses alternative iff source delta>0. Eight-discovery-world selector chooses alternative iff sum paired Heart gains>0; ties use parent. Compare both on eight separately registered confirmation worlds. Also report original-label sign retention, between-world variance, per-stratum outcomes and family-level paired uncertainty. No model or threshold selection.',
        controls='Replan both source actions in every family with worldSeed=original seed; demand exact original full suffix and terminal. Before main run, first two pairs (4 plans) pass. Replay every synthetic suffix via companion initialization and frozen original native action execution; recompute every parent outside decision. Repeat worlds 0 and 8 for first family of each stratum (12 additional plans).',
        budgets=dict(main_synthetic=768,natural_equivalence_controls=48,synthetic_repeats=12,total_plans=828),
        stopping='One fixed diagnostic. Report all 24 families and 16 worlds, retain every fault. No parameter/budget/seed expansion. This does not authorize adopting a policy. If multiple-future choice fails to improve independent-future outcomes, close this teacher recipe rather than fit another network to it.',
        policy_adoption=False,unseen_acceptance_games=0)
    M.put(root/'protocol.json',plan)
    print(dict(status='prepared',families=len(selected),binary=str(binary)),flush=True)


def checked(root):
    plan=E.read(root/'protocol.json')
    E.require(plan['design']==DESIGN,'recipe changed')
    for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'bound input changed: '+path)
    return plan


def load(root):
    plan=checked(root);x=D.runtime(plan['runtime']);parent=E.parent_model(x)
    sys.path.insert(0,str(root));native=importlib.import_module('heart_future_battles')
    return plan,x,parent,native


@contextmanager
def future_solver(sts,native,world):
    original=sts.resolve_battle_recorded
    sts.resolve_battle_recorded=lambda gc,sims,mult:native.resolve_battle(gc,sims,mult,world)
    try:yield
    finally:sts.resolve_battle_recorded=original


def source_state(x,assignment):
    reference=assignment['reference'];row=assignment['row']
    E.require(E.sha(reference['path'])==reference['sha256'] and
              E.sha(row['record'])==assignment['record_sha256'],'episode source changed')
    source=E.read(reference['path']);prefix=source['prefix'][:row['index']]
    gc=x.R.replay(row['seed'],prefix,x.config);x.R.clock_input(gc,x.config)
    E.require(x.R.fingerprint(gc)==assignment['before'],'root state mismatch')
    return source,prefix,gc


def audit(x,parent,native,assignment,world,action,run):
    source,prefix,gc=source_state(x,assignment)
    step=x.R.sts.GameAction(action&0xffffffff);E.require(step.is_valid(gc),'illegal root action');step.execute(gc)
    outside=0;transitions=0;battles=0;encounters=[]
    for record in run['prefix']:
        x.R.clock_input(gc,x.config)
        E.require(x.R.fingerprint(gc)==record['before'],'synthetic replay state/RNG mismatch')
        if record['kind']=='battle':
            before=x.R.fingerprint(gc);battle=native.init_battle(gc,world)
            E.require(x.R.fingerprint(gc)==before,'future initializer mutated real context')
            encounters.append(str(gc.encounter).split('.')[-1])
            for bits in record['actions']:
                native_action=x.R.sts.SearchAction.from_bits(bits&0xffffffff)
                E.require(native_action.is_valid(battle),'recorded battle action invalid')
                native_action.execute(battle);transitions+=1
            E.require(int(battle.outcome)==record['outcome'] and int(battle.turn)+1==record['turns'],
                      'synthetic battle terminal mismatch')
            battle.exit_battle(gc);battles+=1
        else:
            actions=list(x.R.sts.get_legal_game_actions(gc));_,descs,_=x.A.build_choices(gc)
            chosen=parent.choose(gc,x.A.obs_vec(gc),actions,descs)
            E.require(int(actions[chosen].bits)==record['action'],'outside continuation differs from parent')
            x.R.replay_step(gc,record,x.config);outside+=1
    x.R.clock_input(gc,x.config)
    E.require(run['error'] is None and run['status'] in ('heart_win','death','act3_without_heart'),
              'incomplete synthetic rollout')
    E.require(x.R.fingerprint(gc)==run['terminal_fingerprint'] and x.R.terminal(gc)==run['status'],
              'synthetic terminal fingerprint mismatch')
    if run['status']=='heart_win':
        E.require(all(run['keys']) and 'THE_HEART' in encounters,'invalid Heart outcome')
    return dict(status='passed',outside_choices=outside,battle_actions=transitions,battles=battles)


def execute_pair(job):
    root=Path(job['root']);assignment=job['assignment'];index=job['world_index'];seed=assignment['row']['seed']
    world=seed if index<0 else assignment['worlds'][index]
    folder=root/job['stage']/str(seed)/str(index);folder.mkdir(parents=True,exist_ok=True)
    counts=dict(plans=0,simulations=0);results=[]
    try:
        plan,x,parent,native=load(root)
        for arm,action in [('parent',assignment['parent_action']),('alternative',assignment['row']['action'])]:
            source,prefix,gc=source_state(x,assignment)
            root_action=x.R.sts.GameAction(action&0xffffffff)
            E.require(root_action.is_valid(gc),'invalid assigned root action');root_action.execute(gc)
            cfg=dict(x.config,max_steps=x.config['max_steps']-len(prefix)-1,
                     episode_seconds=DESIGN['rollout_seconds'])
            counts['plans']+=1
            with future_solver(x.R.sts,native,world):
                run=x.R.rollout(seed,cfg,gc=gc,net=parent,record=True,record_samples=False)
            x.R.clock_input(gc,x.config)
            run.update(terminal_fingerprint=x.R.fingerprint(gc),future_seed=world,synthetic=index>=0)
            counts['simulations']+=run['simulations'];M.put(folder/(arm+'-attempt.json.gz'),run)
            verification=audit(x,parent,native,assignment,world,action,run)
            if index<0:
                expected=source if arm=='parent' else E.read(assignment['row']['record'])['run']
                E.require(run['prefix']==expected['prefix'][assignment['row']['index']+1:] and
                          run['terminal_fingerprint']==expected['terminal_fingerprint'],
                          'zero-intervention native control differs')
            if job['stage']=='repeat':
                old=E.read(root/'worlds'/str(seed)/str(index)/(arm+'-attempt.json.gz'))
                E.require(run['prefix']==old['prefix'] and run['terminal_fingerprint']==old['terminal_fingerprint'],
                          'fresh synthetic plan repeat differs')
            results.append(dict(arm=arm,win=int(run['status']=='heart_win'),status=run['status'],
                                simulations=run['simulations'],verification=verification))
        report=dict(status='complete',seed=seed,world_index=index,original_delta=assignment['row']['delta'],
                    gain=results[1]['win']-results[0]['win'],arms=results,**counts)
    except Exception:
        report=dict(status='fault',seed=seed,world_index=index,error=traceback.format_exc(),arms=results,**counts)
    M.put(folder/'result.json',report)
    return report


def preflight(root):
    plan,x,parent,native=load(root);assignments=E.read(root/'assignments-private.json');checks=[]
    for assignment in assignments[:2]:
        source,prefix,gc=source_state(x,assignment)
        # Find an actual battle on the original recorded suffix without planning.
        for step in source['prefix'][assignment['row']['index']:]:
            x.R.clock_input(gc,x.config)
            if step['kind']=='battle':break
            x.R.replay_step(gc,step,x.config)
        before=x.R.fingerprint(gc);a=x.R.sts.BattleContext();a.init(gc)
        b=native.init_battle(gc,source['seed']);c=native.init_battle(gc,assignment['worlds'][0])
        E.require(before==x.R.fingerprint(gc) and B.signature(a)==B.signature(b),
                  'native type/zero-intervention initializer differs')
        E.require(dict(a.rng_states)!=dict(c.rng_states),'alternative future did not change RNG')
        checks.append(dict(seed=source['seed'],zero_signature_identical=True,root_unchanged=True,
                           future_rng_changed=True))
    reports=[execute_pair(dict(root=str(root),assignment=a,world_index=-1,stage='controls')) for a in assignments[:2]]
    status='passed' if all(r['status']=='complete' for r in reports) else 'failed'
    result=dict(status=status,initializer_checks=checks,controls=reports,plans=sum(r['plans'] for r in reports),
                protocol_sha256=E.sha(root/'protocol.json'))
    M.put(root/'preflight.json',result);print(result,flush=True)


def decision_metrics(assignments,reports):
    lookup={(r['seed'],r['world_index']):r for r in reports};families=[]
    for assignment in assignments:
        seed=assignment['row']['seed'];gains=[lookup[seed,i]['gain'] for i in range(16)]
        discovery=sum(gains[:8])/8;confirmation=sum(gains[8:])/8
        original_select=assignment['row']['delta']>0;averaged_select=discovery>0
        families.append(dict(seed=seed,original_delta=assignment['row']['delta'],gains=gains,
            discovery_gain=discovery,confirmation_gain=confirmation,mean_gain=sum(gains)/16,
            original_select=original_select,averaged_select=averaged_select,
            original_confirmation_gain=original_select*confirmation,
            averaged_confirmation_gain=averaged_select*confirmation,
            confirmation_improvement=(averaged_select-original_select)*confirmation))
    n=len(families)
    return dict(families=families,assigned_families=n,
        original_confirmation_gain=sum(f['original_confirmation_gain'] for f in families)/n,
        averaged_confirmation_gain=sum(f['averaged_confirmation_gain'] for f in families)/n,
        confirmation_improvement=sum(f['confirmation_improvement'] for f in families)/n,
        selected_original=sum(f['original_select'] for f in families),
        selected_averaged=sum(f['averaged_select'] for f in families),
        positive_original_not_positive_across_worlds=sum(f['original_delta']>0 and f['mean_gain']<=0 for f in families),
        negative_original_not_negative_across_worlds=sum(f['original_delta']<0 and f['mean_gain']>=0 for f in families))


def run(root):
    checked(root);pre=E.read(root/'preflight.json')
    E.require(pre['status']=='passed' and pre['protocol_sha256']==E.sha(root/'protocol.json'),'preflight required')
    assignments=E.read(root/'assignments-private.json');started=time.monotonic();reports=list(pre['controls'])
    jobs=[dict(root=str(root),assignment=a,world_index=-1,stage='controls') for a in assignments[2:]]
    jobs += [dict(root=str(root),assignment=a,world_index=i,stage='worlds') for a in assignments for i in range(16)]
    with ProcessPoolExecutor(max_workers=DESIGN['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
        futures=[pool.submit(execute_pair,j) for j in jobs]
        for future in as_completed(futures):
            reports.append(future.result())
            M.put(root/'status.json',dict(status='running',complete=len(reports),assigned=408,
                faults=sum(r['status']=='fault' for r in reports),seconds=time.monotonic()-started))
            if len(reports)%24==0:print(E.read(root/'status.json'),flush=True)
            E.require(time.monotonic()-started<DESIGN['seconds'],'stage deadline')
    repeats=[]
    if all(r['status']=='complete' for r in reports):
        for a in assignments[::8]:
            for i in (0,8):repeats.append(execute_pair(dict(root=str(root),assignment=a,world_index=i,stage='repeat')))
    all_reports=reports+repeats;faults=[r for r in all_reports if r['status']=='fault']
    worlds=[r for r in reports if r['world_index']>=0]
    metrics=decision_metrics(assignments,worlds) if not faults else None
    result=dict(status='complete' if not faults and len(repeats)==6 else 'incomplete_faults',
        plans=sum(r['plans'] for r in all_reports),simulations=sum(r['simulations'] for r in all_reports),
        controls=len(reports)-len(worlds),synthetic_pairs=len(worlds),repeat_pairs=len(repeats),
        faults=faults,seconds=time.monotonic()-started,metrics=metrics,policy_adoption=False,unseen_acceptance_games=0)
    E.require(result['plans']<=828,'planning budget exceeded');M.put(root/'result.json',result)
    print({k:v for k,v in result.items() if k not in ('metrics','faults')},flush=True)
    if metrics:print({k:v for k,v in metrics.items() if k!='families'},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','preflight','run'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--source',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.source.resolve())
    elif args.command=='preflight':preflight(root)
    else:run(root)
