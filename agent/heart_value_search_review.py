"""Reconcile P210 raw attempts, denominators, paired results and real costs."""
import argparse
from collections import Counter
from fractions import Fraction
import math
from pathlib import Path

import heart_value_search_evaluation as V

E,M=V.E,V.M


def comparison(candidate,reference):
    cells=Counter(zip(candidate,reference));g=cells[True,False];l=cells[False,True];n=g+l
    # Sum the binomial tail exactly before the final float conversion. Rounding
    # each term can differ by one ULP from the separately computed raw result.
    probability=1. if n==0 else float(min(Fraction(1),sum(Fraction(math.comb(n,j),2**n) for j in range(min(g,l)+1))*2))
    return dict(families=len(candidate),wins=sum(candidate),reference_wins=sum(reference),positive=g,negative=l,net=g-l,p=probability)


def review(root):
    plan=V.checked(root);data=E.read(root/'result.json');fit=E.read(root/'fit/result.json')
    tactical=E.read(root/'search/tactical/result.json');whole=E.read(root/'search/whole/result.json');pre=E.read(root/'search/preflight.json')
    E.require(all(r['status']=='complete' for r in (data,fit,tactical,whole)) and pre['status']=='passed','stage incomplete or faulted')
    learning=E.read(root/'fit/protocol.json')
    for path,digest in learning['hashes'].items():E.require(E.sha(path)==digest,'fitting source changed')
    for path,digest in learning['sources'].items():E.require(E.sha(path)==digest,'fitted labels changed')
    E.require(E.sha(root/'fit/model.npz')==fit['export_sha256'] and E.sha(root/'fit/model.pt')==fit['checkpoint_sha256'],'model changed')
    assignments=E.read(root/'assignments-private.json');collection=[]
    for a in assignments:
        r=E.read(root/'collection'/str(a['reference']['seed'])/'result.json')
        E.require(r['status']=='complete' and r['role']==a['role'] and r['seed']==a['reference']['seed'],'collection assignment mismatch');collection.append(r)
    E.require(len(collection)==320 and sum(r['rows'] for r in collection)==data['rows'],'data denominator differs')
    E.require(sum(r['simulations'] for r in collection)+E.read(root/'preflight.json')['simulations']==data['simulations'],'data cost differs')
    references=E.read(root/'search/evaluation-private.json');seeds=[r['seed'] for r in references];parent=[];parent_cost=0;parent_deaths=Counter()
    for ref in references:
        E.require(E.sha(ref['path'])==ref['sha256'],'parent source changed');run=E.read(ref['path'])
        parent.append(run['status']=='heart_win');parent_cost+=run['simulations']
        if run['status']=='death':parent_deaths[run['act']]+=1
    E.require(len(seeds)==len(set(seeds))==128 and sum(parent)==20,'parent denominator')
    outcomes={};costs={};attempts=0;trajectory_steps=0;combat_actions=0;outside_choices=0;replanned_wins=0
    costs_keys=('simulations','search_transitions','prior_transitions','predictions','search_seconds','expanded_nodes','replans')
    ending_counts={}
    for arm in V.ARMS:
        outcomes[arm]=[];costs[arm]={'first':Counter(),'repeat':Counter()};ending_counts[arm]=Counter()
        for ref in references:
            seed=ref['seed'];folder=root/'search/whole'/arm/str(seed);report=E.read(folder/'result.json')
            E.require(report['status']=='complete' and report['seed']==seed and report['arm']==arm,'whole assignment mismatch')
            paths=['first','repeat'] if report['heart'] else ['first'];expected_simulations=0
            first=None
            for attempt in paths:
                attempts+=1;run=E.read(folder/attempt/'run.json.gz');raw=E.read(folder/attempt/'attempt.json.gz')
                E.require({k:v for k,v in run.items() if k!='audit'}==raw,'audit changed attempted policy trajectory')
                E.require(run['seed']==seed and run['combat_arm']==arm and run['combat_model_sha256']==fit['export_sha256'],'wrong whole policy')
                E.require(not run['error'] and run['status'] in ('heart_win','death','act3_without_heart'),'fault treated as outcome')
                E.require(run['audit']['state_rng_terminal'],'missing whole native replay')
                if run['status']=='heart_win':
                    E.require(all(run['keys']) and len(set(run['audit']['act3_bosses']))==2 and run['audit']['act4']==['SHIELD_AND_SPEAR','THE_HEART'],'incomplete Heart route')
                if attempt=='repeat':
                    E.require(run['prefix']==first['prefix'] and run['terminal_fingerprint']==first['terminal_fingerprint'],'winner repeat differs');replanned_wins+=1
                else:
                    first=run;outcomes[arm].append(run['status']=='heart_win');ending_counts[arm][run['status']+':act'+str(run['act'])]+=1
                    E.require((run['status']=='heart_win')==report['heart'],'reported win differs')
                battles=[s for s in run['prefix'] if s['kind']=='battle'];outside_choices+=len(run['prefix'])-len(battles)
                files=sorted((folder/attempt).glob('battle-*.json'));E.require(len(files)==len(battles),'battle ledger missing')
                tally=Counter()
                for path,step in zip(files,battles):
                    saved=E.read(path);E.require(saved['status']=='complete' and all(saved[k]==step[k] for k in ('actions','simulations','turns','outcome')),'battle attempt differs from trajectory')
                    for key in costs_keys:tally[key]+=saved['cost'][key]
                    combat_actions+=len(step['actions'])
                E.require(tally['simulations']==run['simulations'],'run simulation count differs')
                tally['games']+=1;tally['game_seconds']+=run['seconds'];tally['battles']+=len(battles);costs[arm][attempt].update(tally)
                expected_simulations+=run['simulations'];trajectory_steps+=len(run['prefix'])
            E.require(report['attempts']==len(paths) and report['simulations']==expected_simulations,'whole report costs differ')
    stats={arm:comparison(outcomes[arm],parent) for arm in V.ARMS};contrast=comparison(outcomes['learned'],outcomes['constant'])
    E.require(stats==whole['arms'] and contrast==whole['learned_vs_constant'],'paired statistics differ')
    E.require(attempts==whole['attempts']==256+replanned_wins,'planning attempt count differs')
    E.require(sum(c['first']['simulations']+c['repeat']['simulations'] for c in costs.values())==whole['simulations'],'whole cost total differs')
    roots=E.read(plan['tactical_path']);tactical_cost=0;tactical_counts={arm:{g:Counter() for g in ('fatal','surviving')} for arm in V.ARMS}
    for arm in V.ARMS:
        for assignment in roots:
            folder=root/'search/tactical'/arm/str(assignment['reference']['seed']);r=E.read(folder/'result.json');raw=E.read(folder/'attempt.json')
            E.require(r['status']=='complete' and r['outcome']==raw['outcome'] and r['simulations']==raw['simulations'],'tactical attempt mismatch')
            tactical_cost+=raw['simulations'];group=tactical_counts[arm][assignment['group']];group['assigned']+=1;group['survived']+=r['survived']
    E.require(tactical_counts==tactical['arms'] and tactical_cost==tactical['simulations'],'tactical totals differ')
    gate={arm:s['net']>=8 and s['p']<.025 for arm,s in stats.items()};E.require(gate==whole['adoption_gate'],'gate differs')
    diagnostics={};diagnostic_simulations=0
    for name in ('handoff-audit','plan-retention-audit','handoff-followup'):
        path=root/name/'result.json'
        if path.exists():
            diagnostic=E.read(path);E.require(diagnostic['status']=='complete','additional diagnostic incomplete')
            amount=diagnostic.get('new_simulations',diagnostic.get('simulations',0));diagnostic_simulations+=amount
            if name=='handoff-followup':
                attempts_paths=[root/name/(arm+'-attempt.json.gz') for arm in ('stock','alternative')]
                if diagnostic['winner_replans']:attempts_paths.append(root/name/'repeat-attempt.json.gz')
                attempts_rows=[E.read(p) for p in attempts_paths]
                E.require(sum(r['simulations'] for r in attempts_rows)==amount and len(attempts_rows)==diagnostic['calls'],'causal follow-up cost differs')
                E.require(diagnostic['heart_gain']==int(attempts_rows[1]['status']=='heart_win')-int(attempts_rows[0]['status']=='heart_win'),'causal follow-up outcome differs')
            diagnostics[name]=dict(result_sha256=E.sha(path),simulations=amount,planning_calls=diagnostic.get('calls',diagnostic.get('new_searches',0)))
    core_simulations=data['simulations']+pre['simulations']+tactical_cost+whole['simulations']
    result=dict(status='complete',data_rows=data['rows'],data_families=320,data_root_searches=data['searches'],
        verification_transitions=sum(r['verification_transitions'] for r in collection),
        data_tree_transitions=sum(k['search_transitions'] for r in collection for k in r['roots']),
        fitting_updates=fit['updates'],validation_is_diagnostic=True,tactical=tactical_counts,whole=stats,learned_vs_constant=contrast,
        adoption_gate=gate,recipe_closed=not any(gate.values()),unresolved_faults=0,historical_faults=0,
        data_simulations=data['simulations'],preflight_simulations=pre['simulations'],tactical_simulations=tactical_cost,
        whole_simulations=whole['simulations'],core_experiment_simulations=core_simulations,
        additional_diagnostics=diagnostics,diagnostic_simulations=diagnostic_simulations,total_new_simulations=core_simulations+diagnostic_simulations,
        natural_games=256,natural_winner_replans=replanned_wins,stock_natural_controls=2,
        reviewed_trajectory_steps=trajectory_steps,reviewed_combat_actions=combat_actions,reviewed_outside_choices=outside_choices,
        costs_by_arm=costs,parent_reference_simulations=parent_cost,parent_deaths_by_act=parent_deaths,ending_counts=ending_counts,
        review_new_planning_calls=0,policy_adoption=False,unseen_acceptance_games=0,
        limits='Historical development cohort, not independent acceptance. Native trajectory witnesses verified during execution; this review reconciles raw artifacts without another MCTS or native trajectory replay. Original Java global parity is not established.',
        hashes={str(p):E.sha(p) for p in (Path(__file__).resolve(),root/'result.json',root/'fit/result.json',root/'search/tactical/result.json',root/'search/whole/result.json',root/'search/protocol.json')})
    M.put(root/'search/artifact-review.json',result);M.put(root/'search/status.json',dict(status='reviewed',adoption_gate=gate,policy_adoption=False,unseen_acceptance_games=0))
    print({k:v for k,v in result.items() if k not in ('costs_by_arm','hashes','limits')},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path)
    review(parser.parse_args().root.resolve())
