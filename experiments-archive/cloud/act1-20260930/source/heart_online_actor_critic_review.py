"""Reconcile P211 real trajectories, on-policy provenance and learning records.

No game, MCTS, new actor update or new critic fit is run by this review.
"""
import argparse
from collections import Counter
from fractions import Fraction
import math
from pathlib import Path
import time

import numpy as np
import torch

import heart_online_actor_critic as P

E=P.E


def paired(candidate,reference):
    E.require(len(candidate)==len(reference),'paired denominator differs')
    counts=Counter(zip(candidate,reference));g=counts[True,False];l=counts[False,True];n=g+l
    probability=1. if n==0 else float(min(Fraction(1),2*sum(Fraction(math.comb(n,j),2**n) for j in range(min(g,l)+1))))
    return dict(families=len(candidate),wins=sum(candidate),reference_wins=sum(reference),positive=g,negative=l,net=g-l,p=probability)


def stage(root,name):
    folder=root/'execution'/name;assignment=E.read(folder/'assignments.json');result=E.read(folder/'result.json')
    E.require(result['status']=='complete' and result['faults']==0 and len(assignment)==len(result['rows'])==result['assigned'],
              'stage assignment incomplete')
    tally=Counter();endings=Counter();outcomes=[]
    for job,report in zip(assignment,result['rows'],strict=True):
        out=Path(job['output']);E.require(E.read(out/'result.json')==report and report['status']=='complete','job report differs')
        E.require(report['seed']==job['seed'] and report['arm']==job['arm'],'job identity differs')
        E.require(E.sha(job['actor'])==job['actor_sha256'],'collecting policy changed')
        for path,sha in report['artifact_hashes'].items():E.require(E.sha(path)==sha,'raw evidence changed')
        attempts=['first','repeat'] if report['heart'] or job.get('force_repeat') else ['first']
        E.require(report['attempts']==len(attempts),'missing or extra cold replan')
        simulations=0;seconds=0.;first=None
        for label in attempts:
            raw=E.read(out/(label+'-attempt.json.gz'));run=E.read(out/(label+'.json.gz'))
            E.require({k:v for k,v in run.items() if k!='audit'}==raw,'auditing changed the attempted trajectory')
            E.require(run['seed']==job['seed'] and run['checkpoint_sha256']==job['actor_sha256'] and
                run['policy_sampling_seed']==job['sampling_seed'] and run['status'] in P.TERMINALS and not run.get('error'),
                'wrong complete-policy attempt')
            E.require(run['audit']['state_rng_terminal'] and run['audit']['public_policy_verified'],'native proof missing')
            decisions=sum(s['kind']=='outside' for s in run['prefix'])
            E.require(decisions==len(run['samples'])==run['audit']['choices'],'decision count differs')
            for sample in run['samples']:
                n=len(sample['descriptors']);p=np.asarray(sample['probabilities'])
                E.require(len(p)==n and 0<=sample['chosen']<n and np.isfinite(p).all() and (p>=0).all() and
                    abs(float(p.sum())-1)<1e-10,'invalid saved legal policy')
                E.require(abs(math.log(p[sample['chosen']])-sample['log_probability'])<1e-12,'saved likelihood differs')
            battles=[s for s in run['prefix'] if s['kind']=='battle']
            E.require(sum(s['simulations'] for s in battles)==run['simulations'],'native battle cost differs')
            if run['status']=='heart_win':
                E.require(all(run['keys']) and len(set(run['audit']['act3_bosses']))==2 and
                    run['audit']['act4']==['SHIELD_AND_SPEAR','THE_HEART'],'incomplete Heart chain')
            if first is not None:
                E.require(run['prefix']==first['prefix'] and run['samples']==first['samples'] and
                    run['terminal_fingerprint']==first['terminal_fingerprint'],'cold complete replan differs')
                tally['winner_replans']+=int(first['status']=='heart_win')
                tally['other_replans']+=int(first['status']!='heart_win')
            else:
                first=run;outcomes.append(run['status']=='heart_win');endings[f'{run["status"]}:act{run["act"]}']+=1
                E.require(report['heart']==(run['status']=='heart_win') and report['ending']==run['status'] and report['act']==run['act'],
                    'reported ending differs')
                E.require(report['first_simulations']==run['simulations'] and report['first_seconds']==run['seconds'],'first-game cost differs')
            tally[label+'_simulations']+=run['simulations'];tally[label+'_seconds']+=run['seconds'];tally[label+'_games']+=1
            tally['trajectory_steps']+=len(run['prefix']);tally['outside_choices']+=decisions
            tally['combat_actions']+=sum(len(s['actions']) for s in battles)
            simulations+=run['simulations'];seconds+=run['seconds']
        E.require(simulations==report['simulations'] and math.isclose(seconds,report['seconds'],abs_tol=1e-7),'job accounting differs')
    E.require(tally['first_simulations']+tally['repeat_simulations']==result['simulations'] and
        tally['first_games']+tally['repeat_games']==result['attempts'],'stage accounting differs')
    return dict(costs=dict(tally),endings=dict(endings),wins=sum(outcomes),assigned=len(assignment),
                outcomes=outcomes,wall_seconds=result['seconds'])


def learning(root,plan,spec,roles,completed_rounds=None):
    result=[];critic_updates=0;actor_updates=Counter();maximum_value_error=0.;initial=root/'learning/initial.pt'
    count=P.RECIPE['rounds'] if completed_rounds is None else completed_rounds
    E.require(1<=count<=P.RECIPE['rounds'],'invalid completed learning scope')
    for iteration in range(count):
        for arm in P.ARMS:
            stage_arm='monte_carlo' if iteration==0 else arm
            reports=E.read(root/'execution'/f'fit-{iteration}-{stage_arm}'/'result.json')['rows']
            records,episodes,targets,families=P.load_cohort(reports,roles['fit'])
            out=root/'learning'/arm/f'round-{iteration}';recorded=E.read(out/'episodes.json');update=E.read(out/'update.json')
            E.require(episodes==recorded and len(episodes)==512,'learning cohort differs')
            collecting=initial if iteration==0 else root/'learning'/arm/f'round-{iteration-1}'/'actor.pt'
            E.require({e['collecting_sha256'] for e in episodes}=={E.sha(collecting)},'off-policy actor update')
            E.require(update['training_wins']==sum(e['reward'] for e in episodes) and update['training_games']==512 and
                update['decisions']==len(records) and update['updates']==2*math.ceil(len(records)/128),'training denominator differs')
            path=out/'actor.pt';E.require(E.sha(path)==update['actor_sha256'],'updated actor changed')
            payload=torch.load(path,weights_only=True,map_location='cpu')
            E.require(payload['collecting_sha256']==E.sha(collecting) and payload['spec']==spec and payload['recipe']==P.RECIPE and
                payload['identity']==plan['identity'] and payload['iteration']==iteration and payload['arm']==arm,'actor chain differs')
            actor_updates[arm]+=update['updates']
            E.require(all(float(v['step'])==actor_updates[arm] for v in payload['optimizer']['state'].values()),
                      'optimizer steps did not persist across rounds')
            E.require(all(torch.isfinite(v).all() for v in payload['actor_state'].values()),'nonfinite actor checkpoint')
            archive=np.load(out/'advantages.npz');critic=E.read(out/'critic-report.json')
            E.require(np.array_equal(archive['targets'],targets) and np.array_equal(archive['families'],families),
                      'critic labels/family order differs')
            values=np.zeros(len(records),dtype=np.float64)
            if arm=='temporal':
                states=[P.state_features(r,spec) for r in records];width=spec['state_width']+spec['descriptor_dim']+1
                E.require(len(critic['reports'])==3,'critic fold count differs')
                for fold,report in enumerate(critic['reports']):
                    E.require(report['held_fold']==fold and report['training_families']==[i for i in range(256) if i%3!=fold] and
                        report['updates']==2000,'critic included a held family or changed training budget')
                    model_path=out/f'critic-fold-{fold}.pt';E.require(E.sha(model_path)==report['checkpoint_sha256'],'critic changed')
                    model=P.network(width);model.load_state_dict(torch.load(model_path,weights_only=True,map_location='cpu'))
                    ids=np.flatnonzero(families%3==fold)
                    E.require(report['held_decisions']==len(ids),'held-state denominator differs')
                    with torch.no_grad():
                        for at in range(0,len(ids),128):
                            batch=ids[at:at+128]
                            values[batch]=model(torch.from_numpy(P.dense([states[i] for i in batch],width))).sigmoid()[:,0].numpy()
                    critic_updates+=report['updates']
            else:
                E.require(not critic['reports'] and critic['critic_updates']==0,'MC control trained a state critic')
                for fold in range(3):values[families%3==fold]=np.mean([e['reward'] for e in episodes if e['family']%3!=fold])
            difference=float(np.max(np.abs(values-archive['values'])));maximum_value_error=max(maximum_value_error,difference)
            np.testing.assert_allclose(values,archive['values'],atol=1e-12,rtol=0)
            advantage=np.empty(len(records),dtype=np.float64)
            for episode in episodes:
                lo,hi=episode['begin'],episode['end'];reward=episode['reward']
                if arm=='monte_carlo':advantage[lo:hi]=reward-values[lo:hi]
                else:
                    # Independent discounted accumulation of all later TD errors.
                    deltas=np.r_[values[lo+1:hi],0.]-values[lo:hi];deltas[-1]+=reward
                    for j in range(hi-lo):
                        advantage[lo+j]=sum((.95**k)*float(v) for k,v in enumerate(deltas[j:]))
            np.testing.assert_allclose(advantage,archive['advantages'],atol=1e-12,rtol=0)
            E.require(critic['nonzero_advantages']==int(np.count_nonzero(archive['advantages'])),'advantage count differs')
            result.append(dict(arm=arm,iteration=iteration,decisions=len(records),wins=update['training_wins'],
                               actor_updates=update['updates'],critic_value_max_error=difference))
    return dict(rounds=result,actor_updates=dict(actor_updates),critic_updates=critic_updates,maximum_value_error=maximum_value_error)


def review(root):
    started=time.monotonic();plan=P.checked(root);torch.set_num_threads(2)
    spec=E.read(root/'feature-spec.json');roles=E.read(root/'roles-private.json');whole=E.read(root/'result.json')
    E.require(whole['status']=='complete','learning/evaluation unfinished')
    initial=torch.load(root/'learning/initial.pt',weights_only=True,map_location='cpu')
    torch.manual_seed(P.RECIPE['seed']);expected=P.network(spec['width']).state_dict()
    E.require(initial['identity']==plan['identity'] and initial['spec']==spec and
        all(torch.equal(v,initial['actor_state'][k]) for k,v in expected.items()),'registered initial policy differs')
    preflight=E.read(root/'preflight.json');preflight_stage=E.read(root/'execution/preflight/result.json')
    E.require(preflight['status']=='passed' and preflight['rows']==preflight_stage['rows'] and
        preflight['simulations']==preflight_stage['simulations'],'preflight report differs')
    names=['preflight','fit-0-monte_carlo']+[f'fit-{i}-{arm}' for i in range(1,8) for arm in P.ARMS]
    names+=['evaluation-initial','evaluation-monte_carlo','evaluation-temporal']
    stages={};physical=Counter()
    for name in names:
        stages[name]=stage(root,name);physical.update(stages[name]['costs'])
        print(dict(status='reviewing',stage=name,assigned=stages[name]['assigned']),flush=True)
    E.require(sum(s['assigned'] for n,s in stages.items() if n.startswith('fit-'))==7680,'shared cohort double counted or missing')
    E.require(sum(s['assigned'] for n,s in stages.items() if n.startswith('evaluation-'))==384,'evaluation denominator differs')
    E.require(physical['first_games']==8067 and physical['first_games']+physical['repeat_games']<=16134,'total planning budget differs')
    parent=[]
    for ref in roles['evaluation']:
        E.require(E.sha(ref['path'])==ref['sha256'],'parent reference changed');parent.append(E.read(ref['path'])['status']=='heart_win')
    E.require(sum(parent)==20,'parent reference denominator changed')
    outcomes={arm:stages['evaluation-'+arm]['outcomes'] for arm in ('initial',*P.ARMS)}
    stats={arm:dict(parent=paired(outcomes[arm],parent),initial=paired(outcomes[arm],outcomes['initial'])) for arm in P.ARMS}
    contrast=paired(outcomes['temporal'],outcomes['monte_carlo'])
    gates={arm:all(s['net']>=8 and s['p']<.025 for s in comparisons.values()) for arm,comparisons in stats.items()}
    E.require(stats==whole['comparisons'] and gates==whole['adoption_gate'] and contrast==whole['temporal_vs_monte_carlo'],
              'full-policy comparison differs')
    E.require(whole['initial_vs_parent']==paired(outcomes['initial'],parent) and
        whole['recipe_closed']==(not any(gates.values())) and not whole['policy_adoption'] and
        whole['unseen_acceptance_games']==0,'adoption or initial comparison differs')
    training=learning(root,plan,spec,roles)
    frozen=E.read(root/'frozen-candidates.json')
    for arm,item in frozen.items():E.require(E.sha(item['path'])==item['sha256'],'frozen final candidate changed')
    for item in stages.values():item.pop('outcomes')
    result=dict(status='complete',comparisons=stats,temporal_vs_monte_carlo=contrast,adoption_gate=gates,
        recipe_closed=not any(gates.values()),physical_costs=dict(physical),stages=stages,learning=training,
        total_new_simulations=physical['first_simulations']+physical['repeat_simulations'],
        total_planning_calls=physical['first_games']+physical['repeat_games'],unresolved_faults=0,historical_faults=0,
        policy_adoption=False,unseen_acceptance_games=0,review_new_games=0,review_optimizer_updates=0,
        review_seconds=time.monotonic()-started,
        hashes={str(p):E.sha(p) for p in (Path(__file__).resolve(),root/'result.json',root/'protocol.json',root/'frozen-candidates.json')},
        limits='Reconciles raw native-verified trajectories and independently reconstructs policy comparisons, saved critic inference and temporal advantages. Does not repeat native trajectory replay, actor optimization or critic fitting. Historical development, not unseen acceptance. Simulator only; original Java global parity not established.')
    P.put(root/'artifact-review.json',result);P.put(root/'status.json',dict(status='reviewed',adoption_gate=gates,policy_adoption=False))
    print({k:result[k] for k in ('status','comparisons','adoption_gate','total_new_simulations','total_planning_calls')},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    review(parser.parse_args().root.resolve())
