"""Natural-start evaluation of observed-control actors, with independent logits."""
import argparse
from collections import Counter
from pathlib import Path
import time
import traceback

import numpy as np
import torch
import heart_offline_control as O

T,C,V,E=O.T,O.C,O.V,O.E


def load_policy(checkpoint, x):
    if checkpoint['model_type'] == 'expected_heart_improvement':
        from heart_expected_improvement import ImprovementPolicy
        return ImprovementPolicy(checkpoint, x)
    return O.ControlPolicy(checkpoint, x)


def independent_choice(policy,checkpoint,gc,observation,actions,descriptors):
    parent=policy.base.choose(gc,observation,actions,descriptors)
    row=dict(observation=policy.x.R.sparse([observation[i] for i in policy.spec['observations']]),
             descriptors=[policy.x.R.sparse(d) for d in descriptors])
    improvement = checkpoint['model_type'] == 'expected_heart_improvement'
    width = policy.spec['width'] + (policy.spec['descriptor_dim'] if improvement else 0)
    values=np.zeros((len(actions),width),dtype=np.float32)
    for i in range(len(actions)):
        for j,v in C.sparse_features(row,i,policy.spec):values[i,j]=v
    if improvement:
        values[:, policy.spec['width']:] = np.asarray(descriptors[parent], dtype=np.float32)
    weights=checkpoint['actor_state']
    for layer in ('input','tail.1','tail.3'):
        values=values @ weights[layer+'.weight'].numpy().T+weights[layer+'.bias'].numpy()
        if layer!='tail.3':values=values/(1+np.exp(np.clip(-values,-80,80)))
    if improvement:
        probabilities = np.exp(values - values.max(axis=1, keepdims=True))
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        scores = probabilities[:, 2] - probabilities[:, 0]
        scores[parent] = 0.
    else:
        values[parent,0]+=checkpoint['parent_bonus']
        scores = values[:, 0]
    # Independent support/tie arithmetic; do not invoke production select().
    allowed=[i for i,d in enumerate(row['descriptors']) if i==parent or C.support_key(d,policy.spec) in policy.support]
    chosen=max(allowed,key=lambda i:(float(scores[i]),i==parent,-i))
    return chosen,parent


def audit_route(x,row,policy,checkpoint):
    E.require(row['seed']>=0 and row['status'] in ('death','heart_win','act3_without_heart') and not row.get('error'),
              'not a completed natural game')
    gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,row['seed'],20)
    choices=0;changes=Counter();bosses=[];fourth=[]
    for i,step in enumerate(row['prefix']):
        x.R.clock_input(gc,x.config);before=x.R.fingerprint(gc)
        E.require(before==step['before'],'natural state/RNG differs')
        if step['kind']=='outside':
            actions=list(x.R.sts.get_legal_game_actions(gc));_,desc,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
            expected,parent=independent_choice(policy,checkpoint,gc,obs,actions,desc)
            actual=policy.choose(gc,obs,actions,desc)
            E.require(actual==expected==policy.choose(gc,obs,actions,desc),'native full-run neural choice differs')
            E.require(int(actions[actual].bits)==step['action'],'recorded natural action differs')
            E.require(x.R.fingerprint(gc)==before,'policy changed state/RNG while scoring')
            if actual!=parent:changes[str(x.R.kind(desc[actual]))]+=1
            choices+=1
        else:
            if gc.act==3 and gc.cur_room==x.R.sts.Room.BOSS:bosses.append(gc.encounter.name)
            if gc.act==4:
                E.require(gc.red_key and gc.green_key and gc.blue_key,'Act4 missing keys')
                fourth.append(gc.encounter.name)
        x.R.replay_step(gc,step,x.config)
    x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,row)
    if row['status']=='heart_win':
        E.require(len(bosses)==len(set(bosses))==2,'missing two different Act3 bosses')
        E.require(fourth==['SHIELD_AND_SPEAR','THE_HEART'],'missing full Act4')
    return dict(outside_choices=choices,changed_actions_by_kind=dict(changes),
                act_three_bosses=bosses,act_four=fourth,terminal_state_rng_verified=True)


def first_change(x,old,new):
    for i,(a,b) in enumerate(zip(old['prefix'],new['prefix'])):
        if a==b:continue
        E.require(a['kind']==b['kind']=='outside' and a['before']==b['before'] and a['action']!=b['action'],
                  'first policy divergence is not an outside choice at the same state')
        return dict(kind='noncombat',prefix_index=i)
    E.require(old['prefix']==new['prefix'] and x.P.terminal_signature(old)==x.P.terminal_signature(new),
              'same decisions produced a different terminal')
    return dict(kind='unchanged')


def evaluate_worker(job,config):
    try:
        x=C.D.runtime(job['runtime']);E.require(E.sha(job['checkpoint'])==job['checkpoint_sha256'],'candidate changed')
        cp=torch.load(job['checkpoint'],weights_only=True,map_location='cpu');policy=load_policy(cp,x)
        E.require(cp['provenance']['fold']==T.fold(job['seed']) and
                  job['seed'] not in cp['provenance']['fit_families'],'evaluation family entered its model fit')
        E.require(E.sha(job['reference']['path'])==job['reference']['sha256'],'frozen parent reference changed')
        reference=E.read(job['reference']['path'])
        E.require(reference['seed']==job['seed'] and reference['engine_sha256']==x.identity['engine_sha256'] and
                  reference['checkpoint_sha256']==x.identity['model_sha256'],'wrong paired reference')
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,job['seed'],20)
        row=x.R.rollout(job['seed'],config,gc=gc,net=policy,record=True,record_samples=False)
        x.R.clock_input(gc,config)
        row.update(terminal_fingerprint=x.R.fingerprint(gc),checkpoint_sha256=job['checkpoint_sha256'],
                   engine_sha256=x.identity['engine_sha256'])
        row['audit']=audit_route(x,row,policy,cp);row['first_change']=first_change(x,reference,row)
        if job.get('repeat'):
            E.require(E.sha(job['repeat']['path'])==job['repeat']['sha256'],'original winner changed')
            old=E.read(job['repeat']['path'])
            E.require(row['status']==old['status']=='heart_win' and row['prefix']==old['prefix'] and
                      x.P.terminal_signature(row)==x.P.terminal_signature(old),'fresh NN/MCTS winner does not reproduce')
            row['fresh_replan_matched']=True
        result=row
    except Exception:result=dict(status='evaluation_error',seed=job['seed'],error=traceback.format_exc())
    C.D.runtime(job['runtime']).H.write_json(Path(job['output']),result)


def evaluate(root):
    plan=O.registered(root);graph=Path(plan['source']);source=Path(E.read(graph/'protocol.json')['continuous_source']);out=root/'evaluation';out.mkdir()
    x=C.D.runtime(plan['runtime']);E.proof(root/'learning','completion.json')
    roles=E.read(source/'fit-roles.json');seeds=T.pilot_seeds(roles)
    refs=E.indexed(E.read(source/'fit-references.json'),'seed','reference')
    config=dict(x.config,workers=8)
    E.require(config['simulations']==8000 and config['boss_multiplier']==3 and config['ascension']==20,
              'combat/ascension budget changed')
    jobs=[]
    for arm in plan['arms']:
        for seed in seeds:
            checkpoint=root/'learning'/f'fold-{T.fold(seed)}'/arm/'candidate.pt'
            jobs.append(dict(mode='prefix',arm=arm,seed=seed,runtime=plan['runtime'],reference=refs[seed],
                checkpoint=str(checkpoint),checkpoint_sha256=E.sha(checkpoint),output=str(out/arm/f'{seed}.json.gz')))
    deadline=time.monotonic()+plan['evaluation_timeout_seconds']
    rows=x.H.run_jobs(out,jobs,config,'E154_full_runs',deadline,worker_fn=evaluate_worker)
    E.require(len(rows)==len(jobs),'missing assigned games')
    faults=[dict(seed=j['seed'],arm=j['arm'],status=r['status'],error=r.get('error')) for j,r in zip(jobs,rows)
            if r['status'] not in ('death','heart_win','act3_without_heart') or r.get('error')]
    E.write(out/'faults.json',faults)
    E.require(not faults,'full-run evaluation fault; no missing game becomes a death')
    repetitions=[]
    for job,row in zip(jobs,rows):
        if row['status']=='heart_win':
            repetitions.append(dict(job,repeat=dict(path=job['output'],sha256=E.sha(job['output'])),
                output=str(out/'repeated'/job['arm']/f'{job["seed"]}.json.gz')))
    reruns=x.H.run_jobs(out,repetitions,config,'E154_winner_replans',deadline,worker_fn=evaluate_worker) if repetitions else []
    E.require(len(reruns)==len(repetitions) and all(r['status']=='heart_win' and r.get('fresh_replan_matched') for r in reruns),
              'winning rerun incomplete or different')
    reports={};byarm={}
    for arm in plan['arms']:
        chosen=[r for j,r in zip(jobs,rows) if j['arm']==arm];byarm[arm]=chosen
        E.require([r['seed'] for r in chosen]==seeds,'assigned denominator changed')
        counts=x.B.paired_counts([int(refs[s]['status']=='heart_win') for s in seeds],
                                 [int(r['status']=='heart_win') for r in chosen])
        changes=Counter()
        for r in chosen:changes.update(r['audit']['changed_actions_by_kind'])
        reports[arm]=dict(counts=counts,gate_passed=counts['net_gain']>=8 and counts['exact_p']<.025,
            terminal_statuses=dict(Counter(r['status'] for r in chosen)),
            changed_actions_by_kind=dict(changes),outside_choices=sum(r['audit']['outside_choices'] for r in chosen))
    contrast=x.B.paired_counts([int(r['status']=='heart_win') for r in byarm['cloning']],
                                [int(r['status']=='heart_win') for r in byarm['iql']])
    report=dict(status='complete',families=128,arms=reports,iql_against_cloning=contrast,
        specific_iql_benefit=contrast['net_gain']>=4 and contrast['exact_p']<.05,natural_policy_evaluation_games=256,
        winner_replans=len(repetitions),zero_faults=True,new_training_rollouts=0,
        full_fit_models=0,reserved_development_games=0,unseen_acceptance_games=0,production_adoption=False)
    E.write(out/'report.json',report)
    paths=[Path(j['output']) for j in jobs+repetitions]+[out/'report.json',out/'faults.json']
    E.write(out/'completion-verification.json',dict(status='complete',zero_faults=True,
        hashes={str(p.relative_to(out)):E.sha(p) for p in paths}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    evaluate(parser.parse_args().study.resolve())
