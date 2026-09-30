"""Paired parameter search with the same greedy policy during fit and evaluation.

A 192-parameter residual acts at every noncombat choice. Only complete Heart
returns update it; the base network, heuristics and combat remain frozen.
"""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time
import traceback

import numpy as np
import torch

import heart_early_card_scope as E
import heart_continuous_data as C
import heart_offline_control_evaluation as N

RECIPE = dict(rounds=3, directions=8, families_per_direction=16, dimensions=192,
    seed=2026092383, calibration_families=32, calibration_change_fraction=.02,
    calibration_sigmas=[.125,.25,.5,1.,2.,4.,8.,16.,32.],
    minimum_scale=.01, evaluation_families=128, control_families=4)


def paired_update(theta, directions, positive, negative, sigma):
    """Move by a normalized, paired full-policy reward direction.

    This uses the ES directional estimate with a bounded L1-normalized step,
    not a claim of implementing every detail of a published ES/ARS algorithm.
    Equal paired means produce no update and stop the bounded pilot.
    """
    theta=np.asarray(theta,dtype=np.float64); directions=np.asarray(directions,dtype=np.float64)
    positive=np.asarray(positive,dtype=np.float64); negative=np.asarray(negative,dtype=np.float64)
    E.require(directions.ndim==2 and directions.shape[1:]==theta.shape and positive.shape==negative.shape==(len(directions),),
              'paired parameter shapes differ')
    E.require(np.isfinite(directions).all() and np.isfinite(theta).all() and sigma>0,'invalid parameter perturbation')
    E.require(np.isfinite(positive).all() and np.isfinite(negative).all()
              and ((positive>=0)&(positive<=1)&(negative>=0)&(negative<=1)).all(),'invalid full-game returns')
    delta=positive-negative; mass=float(np.abs(delta).sum())
    return (theta.copy() if mass==0 else theta+sigma*(delta@directions)/mass),mass


class WholePolicy:
    def __init__(self,x,theta=None,scale=None):
        self.x=x;self.base=E.parent_model(x);self.base.requires_grad_(False)
        E.require(self.base.model_type=='first_boss_relic_ranker' and self.base.base.model_type=='card_context_residual',
                  'unexpected parent policy')
        self.theta=np.zeros(192) if theta is None else np.asarray(theta,dtype=np.float64).copy()
        self.scale=np.ones(192) if scale is None else np.asarray(scale,dtype=np.float64).copy()
        self.encoder_weight=self.base.base.net[0].weight.detach().double()
        self.encoder_bias=self.base.base.net[0].bias.detach().double()
        E.require(self.theta.shape==self.scale.shape==(192,) and np.isfinite(self.theta).all()
                  and np.isfinite(self.scale).all() and (self.scale>0).all(),'invalid policy parameters')

    @torch.no_grad()
    def menu(self,gc,observation,actions,descriptors):
        x=self.x;inner=self.base.base
        teacher=x.R.heuristic_choice(gc,actions,descriptors)
        original=inner.with_prior(inner.score(torch.tensor(observation),descriptors),teacher)
        inner_parent=int(original.argmax());parent=self.base.choose(gc,observation,actions,descriptors)
        scores=original.double().numpy()
        if x.J.relic_eligible(gc,descriptors,inner_parent):
            options=[i for i,d in enumerate(descriptors) if x.J.relic_option(d) is not None]
            ids=[x.J.relic_option(descriptors[i]) for i in options]
            if set(ids)<=self.base.support:
                scores=np.full(len(actions),-np.inf)
                for i,identity in zip(options,ids,strict=True):scores[i]=float(self.base.relic_scores[identity])
        rows=torch.cat((torch.tensor([observation]*len(actions)),torch.tensor(descriptors)),1).float()
        features=inner.features(rows)
        encoded=torch.nn.functional.linear(features.double(),self.encoder_weight,self.encoder_bias).relu().numpy()
        # Original logits and original tie-breaking reproduce the complete
        # wrapped parent, including the learned first-boss relic preference.
        E.require(select(scores,parent)==parent,'zero residual does not reproduce parent')
        return scores,encoded,parent

    def choose(self,gc,observation,actions,descriptors):
        scores,encoded,parent=self.menu(gc,observation,actions,descriptors)
        residual=((encoded-encoded.mean(0))/self.scale)@self.theta/np.sqrt(192.)
        return select(scores+residual,parent)


def select(scores,parent):
    values=np.asarray(scores,dtype=np.float64)
    E.require(not np.isnan(values).any() and np.isfinite(values).any(),'invalid action scores')
    tied=np.flatnonzero(values.max()-values<=1e-9)
    return int(parent) if parent in tied else int(tied[0])


def independent_choice(policy,gc,observation,actions,descriptors):
    x=policy.x;inner=policy.base.base
    teacher=x.R.heuristic_choice(gc,actions,descriptors)
    parent=policy.base.choose(gc,observation,actions,descriptors)
    # Preserve the parent's original float32 score computation. Independently
    # reconstruct the learned residual's encoder and matrix products in NumPy.
    raw=inner.with_prior(inner.score(torch.tensor(observation),descriptors),teacher)
    baseline=int(raw.argmax());scores=raw.detach().double().numpy()
    if x.J.relic_eligible(gc,descriptors,baseline):
        options=[i for i,d in enumerate(descriptors) if x.J.relic_option(d) is not None]
        if all(x.J.relic_option(descriptors[i]) in policy.base.support for i in options):
            scores=np.array([float(policy.base.relic_scores[x.J.relic_option(d)])
                if i in options else -np.inf for i,d in enumerate(descriptors)])
    with torch.no_grad():
        features=inner.features(torch.cat((torch.tensor([observation]*len(actions)),torch.tensor(descriptors)),1).float()).numpy()
    # The copied representation uses float64 in both deployment and checking;
    # the original action logits retain the untouched parent's float32 path.
    encoded=np.maximum(features.astype(np.float64)@policy.encoder_weight.numpy().T+policy.encoder_bias.numpy(),0)
    residual=np.sum((encoded-encoded.mean(0))/policy.scale*policy.theta[None,:],axis=1)/np.sqrt(192.)
    return select(scores+residual,parent),parent


def registered(root):
    reg=E.read(root/'registration.json')
    for path,digest in reg['hashes'].items():E.require(E.sha(path)==digest,'bound input changed: '+path)
    E.require(reg['runner_sha256']==E.sha(__file__),'whole-policy runner changed')
    plan=E.read(root/'protocol.json');E.require(plan['recipe']==RECIPE and plan['experiment']=='E183','recipe changed')
    roles=E.read(root/'roles-private.json')
    E.require(set(roles)=={'fit','evaluation'} and all(len(values)==128 for values in roles.values())
              and len(set(roles['fit']+roles['evaluation']))==256,'assigned roles differ')
    E.proof(root/'calibration','completion.json')
    previous=Path(plan['learning_evidence']);review=E.read(previous/'result-review.json')
    E.require(review['status']=='complete_reviewed' and not review['result']['learning_gate_passed']
              and review['learning_completion_sha256']==E.sha(previous/'learning/completion.json'),
              'preceding completed learning evidence changed')
    return plan


def policy_from(x,path,digest):
    E.require(E.sha(path)==digest,'policy artifact changed')
    payload=torch.load(path,map_location='cpu',weights_only=True)
    E.require(payload['model_type']=='whole_policy_residual' and payload['base_identity']==x.identity,'wrong policy artifact')
    return WholePolicy(x,payload['theta'].numpy(),payload['scale'].numpy())


def audit_route(x,run,policy):
    E.require(run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error'),'execution fault is not a reward')
    gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,run['seed'],20)
    choices=0;changes=Counter();bosses=[];fourth=[]
    for step in run['prefix']:
        x.R.clock_input(gc,x.config);before=x.R.fingerprint(gc);E.require(before==step['before'],'state/RNG mismatch')
        if step['kind']=='outside':
            actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
            with torch.no_grad():
                selected,parent=independent_choice(policy,gc,obs,actions,ds)
                actual=policy.choose(gc,obs,actions,ds)
            E.require(actual==selected and int(actions[actual].bits)==step['action'],'native policy choice mismatch')
            E.require(before==x.R.fingerprint(gc),'policy query mutated state/RNG')
            if actual!=parent:changes[f'{gc.act}:{x.R.kind(ds[actual])}']+=1
            choices+=1
        else:
            if gc.act==3 and gc.cur_room==x.R.sts.Room.BOSS:bosses.append(gc.encounter.name)
            if gc.act==4:
                E.require(gc.red_key and gc.green_key and gc.blue_key,'Act4 missing keys');fourth.append(gc.encounter.name)
        x.R.replay_step(gc,step,x.config)
    x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
    if run['status']=='heart_win':E.require(len(set(bosses))==2 and len(set(fourth))==2,'incomplete A20 Heart chain')
    return dict(outside_choices=choices,changes=dict(changes),state_rng_and_terminal_verified=True,
                independent_policy_choices_verified=True)


def worker(job,config):
    try:
        root=Path(job['study']);plan=registered(root);x=C.D.runtime(plan['runtime'])
        policy=policy_from(x,job['policy'],job['policy_sha256'])
        E.require(E.sha(job['reference']['path'])==job['reference']['sha256'],'natural reference changed')
        reference=E.read(job['reference']['path'])
        E.require(reference['engine_sha256']==x.identity['engine_sha256']
                  and reference['checkpoint_sha256']==x.identity['model_sha256'],'wrong natural reference identity')
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,job['seed'],20)
        run=x.R.rollout(job['seed'],config,gc=gc,net=policy,record=True,record_samples=False)
        x.R.clock_input(gc,config)
        run.update(terminal_fingerprint=x.R.fingerprint(gc),checkpoint_sha256=job['policy_sha256'],
            engine_sha256=x.identity['engine_sha256'],search_budget=dict(simulations=8000,boss_multiplier=3,max_replans=256))
        run['audit']=audit_route(x,run,policy);run['first_change']=N.first_change(x,reference,run)
        if job.get('control'):
            E.require(run['prefix']==reference['prefix'] and x.P.terminal_signature(run)==x.P.terminal_signature(reference),
                      'fresh zero-residual control differs')
        if job.get('repeat'):
            old=E.read(job['repeat']['path'])
            E.require(E.sha(job['repeat']['path'])==job['repeat']['sha256'] and run['status']==old['status']=='heart_win'
                      and run['prefix']==old['prefix'] and x.P.terminal_signature(run)==x.P.terminal_signature(old),'winner replan differs')
            run['fresh_replan_matched']=True
        result=run
    except Exception:result=dict(status='evaluation_error',seed=job['seed'],error=traceback.format_exc())
    path=Path(job['output']);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.tmp')
    with gzip.open(temporary,'wt') as stream:json.dump(result,stream,separators=(',',':'))
    temporary.replace(path)


def execute_jobs(x,out,jobs,config,name,deadline):
    rows=x.H.run_jobs(out,jobs,config,name,deadline,worker_fn=worker)
    E.require(len(rows)==len(jobs),'missing assigned games')
    E.require(all(row['status'] in ('heart_win','death','act3_without_heart') and not row.get('error') for row in rows),
              'whole-policy execution fault; no outcome/gradient substitution')
    repeats=[dict(job,repeat=dict(path=job['output'],sha256=E.sha(job['output'])),
                  output=str(Path(job['output']).parent/'repeated'/Path(job['output']).name))
             for job,row in zip(jobs,rows,strict=True) if row['status']=='heart_win' and not job.get('control')]
    reruns=x.H.run_jobs(out,repeats,config,name+'_winner_replans',deadline,worker_fn=worker) if repeats else []
    E.require(len(reruns)==len(repeats) and all(row.get('fresh_replan_matched') for row in reruns),'winner repeat missing')
    E.write(out/(name+'-completion.json'),dict(status='complete',games=len(jobs),winner_replans=len(repeats),
        hashes={job['output']:E.sha(job['output']) for job in jobs+repeats}))
    return rows,len(repeats)


def run(root):
    plan=registered(root);E.require(E.read(root/'preflight.json')['status']=='passed','preflight missing')
    x=C.D.runtime(plan['runtime']);config=dict(x.config,workers=8)
    E.require(config['ascension']==20 and config['simulations']==8000 and config['boss_multiplier']==3,'combat budget changed')
    roles=E.read(root/'roles-private.json');refs=E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'),'seed','reference')
    calibration=torch.load(root/'calibration/parameters.pt',map_location='cpu',weights_only=True)
    scale=calibration['scale'].numpy();sigma=calibration['sigma'];theta=np.zeros(192)
    directions=calibration['directions'].numpy();E.require(directions.shape==(3,8,192),'direction budget differs')
    out=root/'search';out.mkdir();deadline=time.monotonic()+plan['timeout_seconds'];rounds=[];games=0;repeats=0

    def save(name,parameters):
        path=out/name;torch.save(dict(model_type='whole_policy_residual',theta=torch.from_numpy(parameters.copy()),
            scale=torch.from_numpy(scale.copy()),base_identity=x.identity,recipe=RECIPE),path)
        return path,E.sha(path)

    def job(seed,path,digest,folder,**extra):
        return dict(mode='prefix',study=str(root),seed=seed,reference=refs[seed],policy=str(path),policy_sha256=digest,
                    output=str(out/folder/f'{seed}.json.gz'),**extra)

    initial,digest=save('initial.pt',theta)
    controls=[job(seed,initial,digest,'controls',control=True) for seed in roles['fit'][:4]]
    execute_jobs(x,out,controls,config,'parent_controls',deadline);games+=4
    for iteration in range(3):
        eps=directions[iteration];jobs=[];assignment=[]
        for direction in range(8):
            start=((direction+iteration)%8)*16;seeds=roles['fit'][start:start+16];assignment.append(seeds)
            for sign in (1,-1):
                name=f'round-{iteration}/direction-{direction}-sign-{sign}'
                (out/name).mkdir(parents=True)
                path,digest=save(name+'/policy.pt',theta+sign*sigma*eps[direction])
                jobs.extend(job(seed,path,digest,name) for seed in seeds)
        rows,count=execute_jobs(x,out,jobs,config,f'round_{iteration}',deadline);games+=len(jobs);repeats+=count
        means=np.array([np.mean([row['status']=='heart_win' for row in rows[i:i+16]]) for i in range(0,len(rows),16)]).reshape(8,2)
        following,mass=paired_update(theta,eps,means[:,0],means[:,1],sigma)
        record=dict(iteration=iteration,assignment=assignment,positive=means[:,0].tolist(),negative=means[:,1].tolist(),
            directional_mass=mass,updated=bool(mass),before=theta.tolist(),after=following.tolist(),
            complete_games=len(jobs),winner_replans=count)
        E.write(out/f'round-{iteration}/update-private.json',record);rounds.append(record);theta=following
        print({key:value for key,value in record.items() if key not in ('assignment','before','after')},flush=True)
        if mass==0:break
    final,digest=save('candidate.pt',theta)
    updated=any(row['updated'] for row in rounds);evaluated=[];counts=None
    if updated:
        eval_jobs=[job(seed,final,digest,'evaluation') for seed in roles['evaluation']]
        evaluated,count=execute_jobs(x,out,eval_jobs,config,'evaluation',deadline);games+=len(eval_jobs);repeats+=count
        counts=x.B.paired_counts([int(refs[s]['status']=='heart_win') for s in roles['evaluation']],
                                 [int(row['status']=='heart_win') for row in evaluated])
    report=dict(status='complete',experiment='E183',training_families=128,evaluation_families=128,
        parameter_updates=sum(row['updated'] for row in rounds),rounds=len(rounds),trainable_parameters=192,
        sigma=sigma,counts=counts,evaluation_executed=updated,
        learning_gate_passed=bool(updated and counts['net_gain']>=8 and counts['exact_p']<.025),
        new_games=games+repeats,base_games=games,winner_replans=repeats,
        outside_choices=sum(row['audit']['outside_choices'] for row in evaluated),
        changed_evaluation_families=sum(row['first_change']['kind']!='unchanged' for row in evaluated),
        zero_faults=True,candidate_sha256=digest,policy_adoption=False,unseen_acceptance_games=0,limits=plan['limits'])
    E.write(out/'report.json',report)
    E.write(out/'completion.json',dict(status='complete',hashes={str(path.relative_to(out)):E.sha(path) for path in out.rglob('*') if path.is_file()}))
    print(report,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    run(parser.parse_args().study.resolve())
