"""P211: complete on-policy learning with current-policy, cross-family values.

Both arms learn a public-state policy from real A20 Heart returns. The Monte
Carlo arm controls the new representation and initial exploration; only the
temporal arm uses a state critic. No outcome-dependent checkpoint selection.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import gzip
import hashlib
import json
import math
import multiprocessing
from pathlib import Path
import random
import shutil
import time
import traceback

import numpy as np
import torch

import heart_continuous_data as C

E = C.E
ARMS = ('monte_carlo', 'temporal')
RECIPE = dict(rounds=8, fit_families=256, repeats=2, evaluation_families=128,
    initial_alternative_mass=.02, hidden=[128,64], actor_epochs=2,
    actor_batch=128, actor_lr=.0003, critic_updates=2000, critic_batch=128,
    critic_lr=.0003, critic_folds=3, weight_decay=1e-5, clip_ratio=.2,
    old_policy_kl=.1, gradient_norm=1., trace_decay=.95, discount=1.,
    workers=8, seed=20260924211, timeout_seconds=21600)
TERMINALS = ('heart_win', 'death', 'act3_without_heart')


def put(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.tmp')
    with (gzip.open(tmp, 'wt') if path.suffix == '.gz' else tmp.open('w')) as f:
        json.dump(value, f, separators=(',', ':'), allow_nan=False)
    tmp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def network(width, bias=0.):
    net = torch.nn.Sequential(torch.nn.Linear(width,128), torch.nn.SiLU(),
        torch.nn.Linear(128,64), torch.nn.SiLU(), torch.nn.Linear(64,1)).double()
    torch.nn.init.zeros_(net[-1].weight); torch.nn.init.constant_(net[-1].bias,bias)
    return net


def prior(size, parent):
    E.require(size > 0 and 0 <= parent < size, 'invalid parent menu')
    if size == 1: return np.ones(1, dtype=np.float64)
    result = np.full(size, RECIPE['initial_alternative_mass']/(size-1))
    result[parent] = 1-RECIPE['initial_alternative_mass']
    return result


def probabilities(logits):
    logits = np.asarray(logits, dtype=np.float64)
    E.require(logits.ndim == 1 and len(logits) and np.isfinite(logits).all(), 'invalid logits')
    weights = np.exp(logits-logits.max())
    return weights/weights.sum()


def sample(p, uniform):
    E.require(0 <= uniform < 1 and np.isfinite(p).all() and (p >= 0).all(), 'invalid sampling input')
    positive = np.flatnonzero(p > 0); cdf = np.cumsum(p[positive]); cdf[-1] = 1.
    return int(positive[np.searchsorted(cdf,uniform,side='right')])


def public_row(x, observation, descriptors, spec):
    return dict(observation=x.R.sparse([observation[i] for i in spec['observations']]),
                descriptors=[x.R.sparse(d) for d in descriptors])


def state_features(row, spec):
    # Candidate-independent current public state and full legal menu.
    result = list(row['observation']); offset = spec['state_width']; mean = Counter()
    for descriptor in row['descriptors']:
        for i,v in descriptor: mean[int(i)] += float(v)/len(row['descriptors'])
    result += [(offset+i,v) for i,v in sorted(mean.items()) if v]
    result.append((offset+spec['descriptor_dim'],len(row['descriptors'])/64.))
    return result


def dense(rows, width):
    result = np.zeros((len(rows),width), dtype=np.float64)
    for i,row in enumerate(rows):
        if row:
            columns,values = zip(*row); result[i,np.asarray(columns,dtype=np.int64)] = values
    return result


def numpy_forward(net, values):
    state = {k:v.detach().numpy() for k,v in net.state_dict().items()}
    value = np.asarray(values,dtype=np.float64)
    for layer in (0,2,4):
        value = value @ state[f'{layer}.weight'].T+state[f'{layer}.bias']
        if layer != 4:
            # Stable sigmoid, preserving the sign of SiLU's input.
            positive = value >= 0; sigmoid = np.empty_like(value)
            sigmoid[positive] = 1/(1+np.exp(-value[positive]))
            exp = np.exp(value[~positive]); sigmoid[~positive] = exp/(1+exp)
            value = value*sigmoid
    return value[:,0]


class Policy:
    def __init__(self,x,spec,state,sampling_seed,greedy_control=False):
        self.x=x;self.spec=spec;self.parent=E.parent_model(x);self.parent.requires_grad_(False)
        self.net=network(spec['width']);self.net.load_state_dict(state);self.net.eval()
        self.rng=random.Random(sampling_seed);self.samples=[];self.greedy_control=greedy_control

    @torch.no_grad()
    def menu(self,gc,observation,actions,descriptors):
        E.require(len(actions)==len(descriptors)>0,'legal menu mismatch')
        row=public_row(self.x,observation,descriptors,self.spec)
        parent=int(self.parent.choose(gc,observation,actions,descriptors))
        values=dense([C.sparse_features(row,i,self.spec) for i in range(len(actions))],self.spec['width'])
        base=prior(len(actions),parent)
        p=probabilities(np.log(base)+self.net(torch.from_numpy(values))[:,0].numpy())
        return row,parent,p,values

    def choose(self,gc,observation,actions,descriptors):
        row,parent,p,_=self.menu(gc,observation,actions,descriptors)
        uniform=self.rng.random();chosen=parent if self.greedy_control else sample(p,uniform)
        row.update(parent=parent,chosen=chosen,probabilities=p.tolist(),uniform=uniform,
                   log_probability=float(np.log(p[chosen])),action_kind=int(self.x.R.kind(descriptors[chosen])))
        self.samples.append(row);return chosen


def audit(x,run,policy,sampling_seed):
    E.require(run['status'] in TERMINALS and not run.get('error'),'fault is not a reward')
    gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,run['seed'],20)
    generator=random.Random(sampling_seed);cursor=0;bosses=[];fourth=[];maximum=0.;changes=Counter()
    for step in run['prefix']:
        x.R.clock_input(gc,x.config);before=x.R.fingerprint(gc)
        E.require(before==step['before'],'native state/RNG differs')
        if step['kind']=='outside':
            actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc)
            row,parent,p,values=policy.menu(gc,x.A.obs_vec(gc),actions,ds);saved=policy.samples[cursor]
            E.require(all(row[k]==saved[k] for k in ('observation','descriptors')) and parent==saved['parent'],
                      'public inputs differ from native state')
            independent=probabilities(np.log(prior(len(actions),parent))+numpy_forward(policy.net,values))
            maximum=max(maximum,float(np.max(np.abs(p-independent))))
            np.testing.assert_allclose(independent,p,atol=1e-10,rtol=0)
            np.testing.assert_allclose(p,saved['probabilities'],atol=1e-12,rtol=0)
            uniform=generator.random();E.require(uniform==saved['uniform'],'behavior stream differs')
            total=0.;chosen=int(np.flatnonzero(independent>0)[-1])
            for i,amount in enumerate(independent):
                total+=float(amount)
                if uniform<total:chosen=i;break
            if policy.greedy_control:chosen=parent
            E.require(chosen==saved['chosen'] and int(actions[chosen].bits)==step['action'],'deployed action differs')
            E.require(abs(saved['log_probability']-math.log(p[chosen]))<1e-12,'behavior likelihood differs')
            E.require(x.R.fingerprint(gc)==before,'public scoring mutated native state')
            if chosen!=parent:changes[str(x.R.kind(ds[chosen]))]+=1
            cursor+=1
        else:
            if gc.act==3 and gc.cur_room==x.R.sts.Room.BOSS:bosses.append(gc.encounter.name)
            if gc.act==4:
                E.require(gc.red_key and gc.green_key and gc.blue_key,'missing Act4 keys')
                fourth.append(gc.encounter.name)
        x.R.replay_step(gc,step,x.config)
    x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
    E.require(cursor==len(policy.samples),'decision denominator differs')
    if run['status']=='heart_win':
        E.require(len(bosses)==len(set(bosses))==2 and fourth==['SHIELD_AND_SPEAR','THE_HEART'],'incomplete Heart route')
    return dict(state_rng_terminal=True,public_policy_verified=True,choices=cursor,
                maximum_probability_error=maximum,changes=dict(changes),act3_bosses=bosses,act4=fourth)


def checked(root):
    plan=E.read(root/'protocol.json');E.require(plan['recipe']==RECIPE,'training recipe changed')
    for path,sha in plan['hashes'].items():E.require(E.sha(path)==sha,'bound input changed: '+path)
    return plan


def worker(job):
    folder=Path(job['output']);folder.mkdir(parents=True,exist_ok=True)
    started_attempts=0
    try:
        root=Path(job['root']);plan=checked(root);torch.set_num_threads(1)
        x=C.D.runtime(plan['runtime']);spec=E.read(root/'feature-spec.json')
        E.require(E.sha(job['actor'])==job['actor_sha256'],'collecting actor changed')
        payload=torch.load(job['actor'],weights_only=True,map_location='cpu')
        E.require(payload['identity']==x.identity and payload['spec']==spec,'wrong actor/runtime')
        rows=[]
        for attempt in range(2):
            if attempt and not (rows[0]['status']=='heart_win' or job.get('force_repeat')):break
            label='first' if attempt==0 else 'repeat'
            policy=Policy(x,spec,payload['actor_state'],job['sampling_seed'],job.get('control',False))
            gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,job['seed'],20)
            started_attempts+=1
            run=x.R.rollout(job['seed'],x.config,gc=gc,net=policy,record=True,record_samples=False)
            x.R.clock_input(gc,x.config)
            run.update(terminal_fingerprint=x.R.fingerprint(gc),checkpoint_sha256=job['actor_sha256'],
                engine_sha256=x.identity['engine_sha256'],policy_sampling_seed=job['sampling_seed'],
                samples=policy.samples,experiment='P211',arm=job['arm'])
            put(folder/(label+'-attempt.json.gz'),run)
            run['audit']=audit(x,run,policy,job['sampling_seed'])
            if job.get('control'):
                E.require(E.sha(job['reference']['path'])==job['reference']['sha256'],'parent source changed')
                old=E.read(job['reference']['path'])
                E.require(run['prefix']==old['prefix'] and x.P.terminal_signature(run)==x.P.terminal_signature(old),'parent control differs')
            if attempt:
                E.require(run['prefix']==rows[0]['prefix'] and run['samples']==rows[0]['samples'] and
                    run['terminal_fingerprint']==rows[0]['terminal_fingerprint'],'cold replan differs')
            put(folder/(label+'.json.gz'),run);rows.append(run)
        result=dict(status='complete',seed=job['seed'],arm=job['arm'],heart=rows[0]['status']=='heart_win',
            ending=rows[0]['status'],act=rows[0]['act'],attempts=len(rows),
            simulations=sum(r['simulations'] for r in rows),seconds=sum(r['seconds'] for r in rows),
            first_simulations=rows[0]['simulations'],first_seconds=rows[0]['seconds'],
            first_path=str(folder/'first.json.gz'),first_sha256=E.sha(folder/'first.json.gz'),
            artifact_hashes={str(p):E.sha(p) for p in folder.glob('*.json.gz')})
    except Exception:
        error=traceback.format_exc();attempts=[E.read(p) for p in folder.glob('*-attempt.json.gz')]
        result=dict(status='fault',seed=job['seed'],arm=job['arm'],error=error,
            attempts=started_attempts,simulations=sum(r.get('simulations',0) for r in attempts),
            cost_incomplete=len(attempts)!=started_attempts,
            artifact_hashes={str(p):E.sha(p) for p in folder.glob('*.json.gz')})
    put(folder/'result.json',result);return result


def execute(root,name,jobs,deadline):
    out=root/'execution'/name;E.require(not out.exists(),'stage exists; audit before any resumption')
    out.mkdir(parents=True);put(out/'assignments.json',jobs);started=time.monotonic();results={}
    pool=None;futures={};interruption=None
    try:
        E.require(shutil.disk_usage(root).free>4*1024**3,'less than4GiB free before collection')
        if time.monotonic()>=deadline:raise TimeoutError('collection deadline expired before launch')
        pool=ProcessPoolExecutor(max_workers=RECIPE['workers'],mp_context=multiprocessing.get_context('spawn'))
        for i,job in enumerate(jobs):
            if time.monotonic()>=deadline:raise TimeoutError('collection deadline expired during submission')
            futures[pool.submit(worker,job)]=i
        for future in as_completed(futures,timeout=max(0.,deadline-time.monotonic())):
            i=futures[future]
            try:results[i]=future.result()
            except Exception:results[i]=dict(status='fault',seed=jobs[i]['seed'],arm=jobs[i]['arm'],
                                             error=traceback.format_exc(),cost_incomplete=True)
            status=dict(status='collecting',stage=name,complete=len(results),assigned=len(jobs),
                faults=sum(r['status']!='complete' for r in results.values()),seconds=time.monotonic()-started)
            put(root/'status.json',status)
            if len(results)%16==0 or len(results)==len(jobs):print(status,flush=True)
    except BaseException as exc:
        interruption=exc
        if pool is not None:
            for future in futures:future.cancel()
            # Python 3.12 has no public kill_workers(). These are this
            # executor's own processes, never unrelated experiment workers.
            processes=list(pool._processes.copy().values())
            for process in processes:
                if process.is_alive():process.kill()
            pool.shutdown(wait=True,cancel_futures=True)
            for process in processes:process.join()
        # A worker can commit its result before its Future reaches the parent.
        # Preserve that evidence; unfinished assignments remain unknown faults.
        for i,job in enumerate(jobs):
            if i in results:continue
            saved=Path(job['output'])/'result.json'
            try:
                row=E.read(saved)
                E.require(row['seed']==job['seed'] and row['arm']==job['arm'],'saved job identity differs')
                results[i]=row
            except Exception:
                results[i]=dict(status='fault',seed=job['seed'],arm=job['arm'],cost_incomplete=True,
                                error=f'{type(exc).__name__}: {exc}')
    else:
        pool.shutdown(wait=True)
    rows=[results[i] for i in range(len(jobs))]
    completion=dict(status='complete' if interruption is None and all(r['status']=='complete' for r in rows) else 'faulted',
        assigned=len(jobs),faults=sum(r['status']!='complete' for r in rows),seconds=time.monotonic()-started,
        attempts=sum(r.get('attempts',0) for r in rows),simulations=sum(r.get('simulations',0) for r in rows),
        cost_incomplete=any(r.get('cost_incomplete',False) for r in rows),rows=rows)
    if interruption is not None:
        completion['error']=f'{type(interruption).__name__}: {interruption}'
    put(out/'result.json',completion)
    put(root/'status.json',dict(status=completion['status'],stage=name,assigned=len(jobs),faults=completion['faults']))
    if interruption is not None:raise interruption
    E.require(completion['status']=='complete','faulted cohort; no reward substitution')
    return rows


def sampling_seed(role,index,iteration,repeat):
    return int(hashlib.sha256(f'P211:{role}:{index}:{iteration}:{repeat}'.encode()).hexdigest()[:16],16)


def jobs_for(root,refs,actor,arm,role,iteration=0,repeats=1,control=False,force_repeat=False):
    jobs=[]
    for i,ref in enumerate(refs):
        for repeat in range(repeats):
            jobs.append(dict(root=str(root),seed=ref['seed'],reference=ref,actor=str(actor),actor_sha256=E.sha(actor),
                arm=arm,sampling_seed=sampling_seed(role,i,iteration,repeat),control=control,force_repeat=force_repeat,
                output=str(root/'episodes'/role/arm/f'round-{iteration}'/f'{i}-{repeat}')))
    return jobs


def save_actor(path,net,identity,spec,**extra):
    path.parent.mkdir(parents=True,exist_ok=True)
    E.require(not path.exists(),'checkpoint exists')
    torch.save(dict(model_type='P211_public_online_actor',actor_state=net.state_dict(),identity=identity,
                    spec=spec,recipe=RECIPE,**extra),path)


def prepare(root,previous):
    E.require(not root.exists(),'new root required')
    review=E.read(previous/'search/artifact-review.json')
    E.require(review['status']=='complete' and review['recipe_closed'],'P210 not closed')
    old=E.read(previous/'protocol.json');runtime=old['runtime'];x=C.D.runtime(runtime)
    refs=E.read(Path(runtime).parent/'fit-references.json')
    evaluation=E.read(previous/'search/evaluation-private.json');excluded={r['seed'] for r in evaluation}
    tactical=E.read(E.read(previous/'search/protocol.json')['tactical_path'])
    excluded.update(r['reference']['seed'] for r in tactical)
    fit=sorted((r for r in refs if r['seed'] not in excluded),
        key=lambda r:hashlib.sha256(f'P211-family:{r["seed"]}'.encode()).hexdigest())[:256]
    E.require(len(fit)==256 and len(evaluation)==128 and len({r['seed'] for r in fit+evaluation})==384,'family separation failed')
    root.mkdir(parents=True);spec=C.spec_for(x);put(root/'feature-spec.json',spec)
    put(root/'roles-private.json',dict(fit=fit,evaluation=evaluation))
    files=[Path(__file__).resolve(),Path(C.__file__).resolve(),Path(C.D.__file__).resolve(),Path(E.__file__).resolve(),
        previous/'search/artifact-review.json',Path(runtime).parent/'fit-references.json',
        root/'feature-spec.json',root/'roles-private.json',
        Path(__file__).resolve().parents[1]/'tests/test_heart_online_actor_critic.py']
    plan=dict(experiment='P211',runtime=runtime,identity=x.identity,recipe=RECIPE,
        hashes={str(p):E.sha(p) for p in files},
        objective='Undiscounted complete natural A20 Heart binary reward. Zero intermediate reward; death and act3_without_heart are0; execution faults remain unknown.',
        actor='Public allowlisted observation, complete legal-menu mean, candidate descriptor and menu size;5339-style continuous encoder,128/64 SiLU body and zero output head. Prior gives parent.98 and divides.02 over other legal choices. Learned residual acts in log-probability space after this prior. Initial exploration is learnable, not an external epsilon action with vanishing actor gradient.',
        learning='Eight rounds of256 families times2 independent behavior streams per arm. Round0 shared because actors equal. Current-policy data only. Monte Carlo control subtracts a mean from other family folds. Temporal arm fits three state-only critics to the current cohort excluding the predicted family fold; GAE gamma1 lambda.95 uses those predictions. Critic sees public state and menu, not sampled action. Every actor gets2 PPO epochs with persistent AdamW state.',
        critic='Current public observation and menu mean/count;128/64 SiLU sigmoid, fixed2000 AdamW updates per excluded fold. Uniform training family, repeat, then decision. Refit from scratch each round to current-policy outcomes; no model or validation selection.',
        training_games=7680,evaluation_games=384,parent_controls=2,preflight_stochastic_games=1,
        new_plans_max=16134,all_winners_replanned=True,
        evaluation='Freeze initial and both final stochastic policies, then128 historical E191 families with identical independent policy sampling streams. Each final arm needs net>=8 and paired p<.025 against both parent and initial. Report temporal versus Monte Carlo separately; an algorithm mechanism claim is not implied by beating the parent. No intermediate checkpoint evaluation or outcome-based extension.',
        source_references=['https://arxiv.org/abs/1707.06347','https://arxiv.org/abs/1506.02438'],
        limits='This is one coupled learning-regime experiment, not isolation of every change from E191/P201. Prior failed schedules stay closed. Eight-round training outcomes are different policies, not a matched performance curve. Historical development is not unseen acceptance; no final1024 drawn. Simulator only; original Java global parity unestablished.')
    put(root/'protocol.json',plan);torch.manual_seed(RECIPE['seed']);net=network(spec['width'])
    save_actor(root/'learning/initial.pt',net,x.identity,spec,iteration=-1,arm='initial')
    put(root/'status.json',dict(status='prepared',adopted=False,unseen_acceptance_games=0))
    print(dict(status='prepared',width=spec['width'],state_width=spec['state_width']+spec['descriptor_dim']+1,
               actor_parameters=sum(p.numel() for p in net.parameters())),flush=True)


def preflight(root):
    plan=checked(root);roles=E.read(root/'roles-private.json');actor=root/'learning/initial.pt'
    deadline=time.monotonic()+1800
    controls=jobs_for(root,roles['fit'][:2],actor,'parent','preflight-control',control=True)
    stochastic=jobs_for(root,roles['fit'][:1],actor,'initial','preflight-stochastic',force_repeat=True)
    rows=execute(root,'preflight',controls+stochastic,deadline)
    put(root/'preflight.json',dict(status='passed',first_games=3,attempts=sum(r['attempts'] for r in rows),
        simulations=sum(r['simulations'] for r in rows),rows=rows))
    print(dict(status='preflight_passed',attempts=sum(r['attempts'] for r in rows)),flush=True)


def load_cohort(reports,fit):
    records=[];episodes=[];states=[];targets=[];families=[]
    for index,report in enumerate(reports):
        E.require(report['seed']==fit[index//2]['seed'] and E.sha(report['first_path'])==report['first_sha256'],'cohort family/source differs')
        run=E.read(report['first_path']);E.require(run['audit']['public_policy_verified'] and not run.get('error'),'unverified data')
        begin=len(records);selected=[s for s in run['samples'] if len(s['descriptors'])>1]
        E.require(selected,'empty decision trajectory');reward=int(run['status']=='heart_win')
        records.extend(selected);targets.extend([reward]*len(selected));families.extend([index//2]*len(selected))
        episodes.append(dict(begin=begin,end=len(records),reward=reward,family=index//2,
            collecting_sha256=run['checkpoint_sha256'],path=report['first_path'],sha256=report['first_sha256']))
    return records,episodes,np.asarray(targets,dtype=np.float64),np.asarray(families,dtype=np.int64)


def temporal(values,reward,trace_decay=None):
    trace_decay=RECIPE['trace_decay'] if trace_decay is None else trace_decay
    values=np.asarray(values,dtype=np.float64);result=np.empty_like(values);following=0.;following_value=0.
    for i in range(len(values)-1,-1,-1):
        delta=(reward if i==len(values)-1 else 0.)+following_value-values[i]
        result[i]=delta+trace_decay*following;following=result[i];following_value=values[i]
    return result


def fit_critic(states,targets,episodes,held_fold,width,iteration,updates=None):
    eligible=[e for e in episodes if e['family']%3!=held_fold]
    E.require(eligible and all(e['family']%3!=held_fold for e in eligible),'cross-family exclusion failed')
    mean=float(np.mean([e['reward'] for e in eligible]));clipped=min(1-1e-4,max(1e-4,mean))
    torch.manual_seed(RECIPE['seed']+10000+100*iteration+held_fold)
    net=network(width,math.log(clipped/(1-clipped)))
    optimizer=torch.optim.AdamW(net.parameters(),lr=RECIPE['critic_lr'],weight_decay=RECIPE['weight_decay'])
    generator=np.random.default_rng(RECIPE['seed']+20000+100*iteration+held_fold)
    steps=RECIPE['critic_updates'] if updates is None else updates;losses=[]
    # Every family has exactly two episodes, so uniform episodes = uniform family/repeat.
    for step in range(steps):
        drawn=generator.integers(len(eligible),size=RECIPE['critic_batch'])
        indices=[int(generator.integers(eligible[i]['begin'],eligible[i]['end'])) for i in drawn]
        values=torch.from_numpy(dense([states[i] for i in indices],width));labels=torch.from_numpy(targets[indices])
        logits=net(values)[:,0];loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,labels)
        optimizer.zero_grad(set_to_none=True);loss.backward()
        norm=torch.nn.utils.clip_grad_norm_(net.parameters(),RECIPE['gradient_norm'])
        E.require(torch.isfinite(norm) and torch.isfinite(loss),'nonfinite critic update');optimizer.step()
        if step%200==0 or step==steps-1:losses.append(dict(update=step+1,loss=float(loss.detach())))
    return net,dict(held_fold=held_fold,training_families=sorted({e['family'] for e in eligible}),updates=steps,
        initialization_mean=mean,curve=losses)


def advantages(root,out,arm,iteration,records,episodes,targets,families,spec):
    values=np.zeros(len(records),dtype=np.float64);reports=[]
    if arm=='temporal':
        states=[state_features(r,spec) for r in records];width=spec['state_width']+spec['descriptor_dim']+1
        for fold in range(3):
            model,report=fit_critic(states,targets,episodes,fold,width,iteration)
            ids=np.flatnonzero(families%3==fold)
            with torch.no_grad():
                for start in range(0,len(ids),128):
                    batch=ids[start:start+128]
                    values[batch]=model(torch.from_numpy(dense([states[i] for i in batch],width))).sigmoid()[:,0].numpy()
            path=out/f'critic-fold-{fold}.pt';torch.save(model.state_dict(),path)
            report.update(checkpoint_sha256=E.sha(path),held_decisions=len(ids));reports.append(report)
    else:
        for fold in range(3):
            others=[e['reward'] for e in episodes if e['family']%3!=fold]
            values[families%3==fold]=np.mean(others)
    result=np.zeros(len(records),dtype=np.float64)
    for episode in episodes:
        s=slice(episode['begin'],episode['end']);reward=episode['reward']
        result[s]=temporal(values[s],reward) if arm=='temporal' else reward-values[s]
    E.require(np.isfinite(values).all() and np.isfinite(result).all(),'invalid advantage')
    np.savez_compressed(out/'advantages.npz',values=values,advantages=result,targets=targets,families=families)
    put(out/'critic-report.json',dict(arm=arm,reports=reports,decisions=len(records),
        brier=float(np.mean((values-targets)**2)),nonzero_advantages=int(np.count_nonzero(result)),
        metric_is_diagnostic=True,critic_updates=sum(r['updates'] for r in reports)))
    return result


def actor_update(net,optimizer,records,advantage,spec,iteration):
    generator=random.Random(RECIPE['seed']+30000+iteration);updates=0;curves=[]
    for epoch in range(RECIPE['actor_epochs']):
        order=list(range(len(records)));generator.shuffle(order);total=Counter()
        for at in range(0,len(order),RECIPE['actor_batch']):
            ids=order[at:at+RECIPE['actor_batch']];batch=[records[i] for i in ids]
            lengths=[len(r['descriptors']) for r in batch]
            matrix=dense([C.sparse_features(r,j,spec) for r in batch for j in range(len(r['descriptors']))],spec['width'])
            outputs=net(torch.from_numpy(matrix))[:,0].split(lengths)
            logs=[(out+torch.from_numpy(np.log(prior(len(r['descriptors']),r['parent'])))).log_softmax(0)
                  for r,out in zip(batch,outputs,strict=True)]
            selected=torch.stack([log[r['chosen']] for r,log in zip(batch,logs,strict=True)])
            old=torch.tensor([r['log_probability'] for r in batch],dtype=torch.float64)
            a=torch.from_numpy(advantage[ids]);ratio=(selected-old).exp()
            pg=-torch.minimum(ratio*a,ratio.clamp(1-RECIPE['clip_ratio'],1+RECIPE['clip_ratio'])*a).mean()
            kl=torch.stack([torch.nn.functional.kl_div(log,torch.tensor(r['probabilities'],dtype=torch.float64),reduction='sum')
                            for r,log in zip(batch,logs,strict=True)]).mean()
            loss=pg+RECIPE['old_policy_kl']*kl
            optimizer.zero_grad(set_to_none=True);loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(net.parameters(),RECIPE['gradient_norm'])
            E.require(torch.isfinite(loss) and torch.isfinite(norm),'nonfinite actor update');optimizer.step();updates+=1
            total['decisions']+=len(batch);total['pg']+=float(pg.detach())*len(batch);total['kl']+=float(kl.detach())*len(batch)
            total['clipped']+=int(((ratio.detach()-1).abs()>.2).sum())
        curves.append(dict(epoch=epoch,policy_loss=total['pg']/total['decisions'],kl=total['kl']/total['decisions'],
                           clip_fraction=total['clipped']/total['decisions']))
    return dict(updates=updates,decisions=len(records),curve=curves)


def paired(candidate,reference):
    counts=Counter(zip(candidate,reference));g=counts[True,False];l=counts[False,True];n=g+l
    p=1. if not n else min(1.,2*sum(math.comb(n,j) for j in range(min(g,l)+1))/2**n)
    return dict(families=len(candidate),wins=sum(candidate),reference_wins=sum(reference),positive=g,negative=l,net=g-l,p=p)


def run(root):
    plan=checked(root);E.require(E.read(root/'preflight.json')['status']=='passed','preflight required')
    x=C.D.runtime(plan['runtime']);torch.set_num_threads(2);spec=E.read(root/'feature-spec.json');roles=E.read(root/'roles-private.json')
    initial=root/'learning/initial.pt';initial_state=torch.load(initial,weights_only=True)['actor_state']
    networks={arm:network(spec['width']) for arm in ARMS}
    for net in networks.values():net.load_state_dict(initial_state)
    optimizers={arm:torch.optim.AdamW(net.parameters(),lr=RECIPE['actor_lr'],weight_decay=RECIPE['weight_decay']) for arm,net in networks.items()}
    actors={arm:initial for arm in ARMS};deadline=time.monotonic()+RECIPE['timeout_seconds'];rounds=[]
    for iteration in range(RECIPE['rounds']):
        shared=None
        for arm in ARMS:
            if iteration==0 and shared is not None:reports=shared
            else:
                jobs=jobs_for(root,roles['fit'],actors[arm],arm,'fit',iteration,RECIPE['repeats'])
                reports=execute(root,f'fit-{iteration}-{arm}',jobs,deadline)
                if iteration==0:shared=reports
            records,episodes,targets,families=load_cohort(reports,roles['fit'])
            E.require({e['collecting_sha256'] for e in episodes}=={E.sha(actors[arm])},'off-policy cohort')
            out=root/'learning'/arm/f'round-{iteration}';out.mkdir(parents=True)
            put(out/'episodes.json',episodes);a=advantages(root,out,arm,iteration,records,episodes,targets,families,spec)
            update=actor_update(networks[arm],optimizers[arm],records,a,spec,iteration)
            path=out/'actor.pt';save_actor(path,networks[arm],x.identity,spec,iteration=iteration,arm=arm,
                optimizer=optimizers[arm].state_dict(),collecting_sha256=E.sha(actors[arm]))
            update.update(iteration=iteration,arm=arm,training_wins=sum(e['reward'] for e in episodes),
                training_games=len(episodes),actor_sha256=E.sha(path),shared_first_cohort=iteration==0)
            put(out/'update.json',update);rounds.append(update);actors[arm]=path
            put(root/'status.json',dict(status='learning',iteration=iteration,arm=arm,completed_actor_updates=len(rounds)))
            print(update,flush=True);E.require(time.monotonic()<deadline,'training deadline reached')
    put(root/'frozen-candidates.json',dict(initial=dict(path=str(initial),sha256=E.sha(initial)),
        **{arm:dict(path=str(path),sha256=E.sha(path)) for arm,path in actors.items()}))
    outcomes={}
    for arm,path in [('initial',initial),*actors.items()]:
        reports=execute(root,'evaluation-'+arm,jobs_for(root,roles['evaluation'],path,arm,'evaluation'),deadline)
        outcomes[arm]=[r['heart'] for r in reports]
    parent=[E.read(r['path'])['status']=='heart_win' for r in roles['evaluation']]
    stats={arm:dict(parent=paired(outcomes[arm],parent),initial=paired(outcomes[arm],outcomes['initial'])) for arm in ARMS}
    gates={arm:all(s['net']>=8 and s['p']<.025 for s in comparisons.values()) for arm,comparisons in stats.items()}
    put(root/'result.json',dict(status='complete',rounds=rounds,comparisons=stats,adoption_gate=gates,
        temporal_vs_monte_carlo=paired(outcomes['temporal'],outcomes['monte_carlo']),
        initial_vs_parent=paired(outcomes['initial'],parent),recipe_closed=not any(gates.values()),
        policy_adoption=False,unseen_acceptance_games=0,limits=plan['limits']))
    put(root/'status.json',dict(status='complete',adoption_gate=gates,policy_adoption=False,unseen_acceptance_games=0))
    print(dict(status='complete',comparisons=stats,adoption_gate=gates),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','preflight','run'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--previous',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.previous.resolve())
    elif args.command=='preflight':preflight(root)
    else:run(root)
