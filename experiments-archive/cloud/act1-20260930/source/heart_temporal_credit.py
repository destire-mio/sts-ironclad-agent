"""A fixed first-update comparison of grouped, state and temporal advantages.

No actor learns from a changed collecting distribution. State predictions are
the already audited cross-family E195 values for E191's initial 512 games.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import gzip
import json
import multiprocessing
from pathlib import Path
import random
import time
import traceback

import numpy as np
import torch
import heart_whole_policy_gradient as G
import heart_state_baseline as B

E = G.E
ARMS = ('grouped', 'state_mc', 'temporal')
LAMBDA = .95


def put(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with (gzip.open(temp, 'wt') if path.suffix == '.gz' else temp.open('w')) as stream:
        json.dump(value, stream, separators=(',', ':'), allow_nan=False)
    temp.replace(path)


def temporal_advantages(values, reward, trace_decay=LAMBDA):
    values = np.asarray(values, dtype=np.float64)
    E.require(values.ndim == 1 and len(values) and np.isfinite(values).all(), 'invalid state values')
    E.require(reward in (0, 1) and 0 <= trace_decay <= 1, 'invalid complete reward/trace decay')
    result = np.empty_like(values); following_advantage = 0.; following_value = 0.
    for at in range(len(values)-1, -1, -1):
        immediate = reward if at == len(values)-1 else 0.
        delta = immediate + following_value - values[at]
        result[at] = delta + trace_decay * following_advantage
        following_advantage = result[at]; following_value = values[at]
    return result


def corpus(plan):
    source = Path(plan['source']); baseline = Path(plan['baseline'])
    complete = E.read(baseline / 'learning/completion.json')['hashes']
    for name in ('data-private.npz', 'predictions-private.npz', 'source-private.json', 'fold-0.npz', 'fold-1.npz', 'fold-2.npz'):
        E.require(E.sha(baseline/'learning'/name) == complete[name], 'baseline artifact changed')
    data = np.load(baseline/'learning/data-private.npz'); stored = np.load(baseline/'learning/predictions-private.npz')['predictions']
    reconstructed = np.empty_like(stored)
    for fold in range(3):
        mask = data['folds'] == fold
        model = dict(np.load(baseline/f'learning/fold-{fold}.npz'))
        reconstructed[mask] = B.predict(model, data['features'][mask])
    np.testing.assert_allclose(reconstructed, stored, atol=1e-12, rtol=0)
    roles = E.read(source/'roles-private.json'); metadata = E.read(baseline/'learning/source-private.json')['episodes']
    E.require(len(metadata) == 512 and set(roles['fit']).isdisjoint(roles['evaluation']), 'wrong family separation')
    records = []; advantages = {arm: [] for arm in ARMS}; episodes = []; cursor = 0
    rewards = [m['reward'] for m in metadata]
    grouped = np.concatenate([G.leave_one_out(rewards[i:i+4]) for i in range(0,512,4)])
    initial_sha = E.sha(source/'learning/initial.pt')
    for at, meta in enumerate(metadata):
        E.require(E.sha(meta['path']) == meta['sha256'], 'raw training source changed')
        run = E.read(meta['path']); samples = [s for s in run['policy_samples'] if len(s['active']) > 1]
        end = cursor + len(samples); reward = int(run['status'] == 'heart_win')
        E.require(not run.get('error') and run['status'] in ('heart_win','death','act3_without_heart') and
                  run['checkpoint_sha256'] == initial_sha and run['seed'] == roles['fit'][at//4]
                  and meta['begin'] == cursor and meta['end'] == end and meta['reward'] == reward, 'trajectory role/order differs')
        E.require(np.all(data['families'][cursor:end] == at//4) and
                  np.all(data['folds'][cursor:end] == B.family_fold(run['seed'])), 'state model family roles differ')
        values = stored[cursor:end]
        records.extend(samples); advantages['grouped'].extend([grouped[at]]*len(samples))
        advantages['state_mc'].extend(reward-values); advantages['temporal'].extend(temporal_advantages(values,reward))
        episodes.append(dict(seed=run['seed'], begin=cursor, end=end, reward=reward))
        cursor = end
    E.require(cursor == 55473 == len(stored), 'training coverage differs')
    return records, {k:np.asarray(v) for k,v in advantages.items()}, episodes


def fit_records(policy, records, advantages):
    recipe = G.RECIPE
    optimizer = torch.optim.AdamW(policy.net.parameters(), lr=recipe['learning_rate'], weight_decay=recipe['weight_decay'])
    generator = random.Random(recipe['seed']+1000); updates=0; curves=[]
    width = policy.net[0].in_features
    for epoch in range(recipe['epochs']):
        order=list(range(len(records))); generator.shuffle(order); losses=[]
        for start in range(0,len(order),recipe['batch_size']):
            indices=order[start:start+recipe['batch_size']]
            batch=[dict(records[i], advantage=float(advantages[i])) for i in indices]
            lengths=[len(r['active']) for r in batch]; values=np.zeros((sum(lengths),width),dtype=np.float64); cursor=0
            for row in batch:
                for sparse in row['features']:
                    for col,value in sparse: values[cursor,col]=value
                    cursor+=1
            features=torch.from_numpy(values); reference=policy.initial(features).detach().squeeze(-1)
            residual=(policy.net(features).squeeze(-1)-reference).split(lengths)
            logits=[(torch.tensor(row['base_scores'],dtype=torch.float64)+v)/policy.temperature
                    for row,v in zip(batch,residual,strict=True)]
            loss,_,_,_=G.objective(logits,batch)
            optimizer.zero_grad(set_to_none=True);loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(policy.net.parameters(),recipe['gradient_norm'])
            E.require(torch.isfinite(norm),'nonfinite gradient');optimizer.step();updates+=1
            losses.append(float(loss.detach()))
        curves.append(dict(epoch=epoch,mean_loss=float(np.mean(losses))))
    return dict(updates=updates,curves=curves,nonzero_advantages=int(np.count_nonzero(advantages)))


def prepare(root, source, baseline):
    E.require(not root.exists(),'new study required');root.mkdir(parents=True)
    hashes={str(path):E.sha(path) for path in [source/'protocol.json',source/'roles-private.json',source/'learning/initial.pt',
        source/'learning/actor-after-0.pt',source/'learning/round-0/update.json',baseline/'result-review.json',
        baseline/'learning/completion.json',Path(G.__file__),Path(B.__file__)]}
    plan=dict(experiment='P201',source=str(source),baseline=str(baseline),runtime=E.read(source/'protocol.json')['runtime'],
        arms=list(ARMS),trace_decay=LAMBDA,discount=1.,runner_sha256=E.sha(__file__),hashes=hashes,
        recipe=G.RECIPE,training_games=0,updates_per_arm=868,trained_arms=3,
        evaluation_families=128,evaluation_games_max=384,winner_replans_max=384,evaluation_controls=2,total_new_games_max=772,
        evaluation_seconds=5400,training_seconds=1800,workers=8,
        decision='A new arm needs net>=8/128 and paired p<.025 against both same-budget grouped actor and greedy parent. Temporal mechanism claim additionally requires net>=4/128 vs state_mc. Historical development only; then independent prospective validation, never automatic adoption.',
        limits='E195 predictive/variance failures remain; predictions are imperfect and temporal estimates biased. This is a new actor-effect test, not revival based on a proxy metric. P200 search recipe stays closed; no P200 future-informed actions enter actor fitting.')
    put(root/'protocol.json',plan);put(root/'status.json',dict(status='prepared',new_games=0,updates=0))
    print(dict(status='prepared',root=str(root)),flush=True)


def checked(root):
    plan=E.read(root/'protocol.json');E.require(E.sha(__file__)==plan['runner_sha256'],'runner changed')
    for path,value in plan['hashes'].items():E.require(E.sha(path)==value,'registered input changed: '+path)
    return plan


def train(root):
    plan=checked(root);torch.set_num_threads(1);x=G.C.D.runtime(plan['runtime']);started=time.monotonic()
    records,advantages,episodes=corpus(plan);out=root/'learning';out.mkdir()
    np.savez(out/'advantages.npz',**advantages);put(out/'episodes.json',episodes)
    initial=torch.load(Path(plan['source'])/'learning/initial.pt',map_location='cpu',weights_only=True)['actor_state']
    reports={}
    for arm in ARMS:
        E.require(time.monotonic()-started < plan['training_seconds'],'training time bound reached')
        policy=G.Policy(x,state=initial,temperature=1.);result=fit_records(policy,records,advantages[arm])
        E.require(result['updates']==plan['updates_per_arm'],'optimizer budget differs')
        if arm=='grouped':
            expected=torch.load(Path(plan['source'])/'learning/actor-after-0.pt',map_location='cpu',weights_only=True)['actor_state']
            error=max(float((policy.net.state_dict()[k]-v).abs().max()) for k,v in expected.items())
            E.require(error < 1e-9,'grouped control does not reproduce old update')
            result['maximum_original_weight_error']=error
        path=out/(arm+'.pt')
        torch.save(dict(model_type='temporal_credit_actor',actor_state=policy.net.state_dict(),base_identity=x.identity,
                        arm=arm,temperature=1.,source_initial_sha256=E.sha(Path(plan['source'])/'learning/initial.pt')),path)
        result['checkpoint_sha256']=E.sha(path);reports[arm]=result
        put(out/(arm+'-training.json'),result);print(dict(arm=arm,**result),flush=True)
    put(out/'completion.json',dict(status='complete',reports=reports,seconds=time.monotonic()-started,
        new_games=0,actor_updates=sum(r['updates'] for r in reports.values()),runner_sha256=E.sha(__file__)))
    put(root/'status.json',dict(status='training_complete',new_games=0))


def evaluation_worker(job):
    folder=Path(job['output']).parent;folder.mkdir(parents=True,exist_ok=True)
    try:
        root=Path(job['root']);plan=checked(root);x=G.C.D.runtime(plan['runtime']);torch.set_num_threads(1)
        if job['arm']=='initial_control':
            path=Path(plan['source'])/'learning/initial.pt'
        else:path=root/'learning'/(job['arm']+'.pt')
        E.require(E.sha(path)==job['checkpoint_sha256'],'candidate changed')
        payload=torch.load(path,map_location='cpu',weights_only=True)
        def one():
            policy=G.Policy(x,state=payload['actor_state'],temperature=1.,sampling_seed=job['sampling_seed'])
            gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,job['seed'],20)
            run=x.R.rollout(job['seed'],x.config,gc=gc,net=policy,record=True,record_samples=False)
            x.R.clock_input(gc,x.config);run['terminal_fingerprint']=x.R.fingerprint(gc)
            run['audit']=G.audit_route(x,run,policy,job['sampling_seed'])
            run.update(checkpoint_sha256=job['checkpoint_sha256'],arm=job['arm'],sampling_seed=job['sampling_seed'])
            return run
        result=one()
        if job['arm']=='initial_control':
            old=E.read(job['reference'])
            E.require(result['prefix']==old['prefix'] and x.P.terminal_signature(result)==x.P.terminal_signature(old),'initial control changed')
        if result['status']=='heart_win':
            rerun=one();E.require(rerun['prefix']==result['prefix'] and x.P.terminal_signature(rerun)==x.P.terminal_signature(result),'winner replan differs')
            put(folder/('replan-'+Path(job['output']).name),rerun);result['winner_replanned']=True
        result['error']=None
    except Exception:
        result=dict(status='fault',seed=job['seed'],arm=job['arm'],error=traceback.format_exc())
    put(job['output'],result)
    return {k:result.get(k) for k in ('status','seed','arm','error','winner_replanned')}


def evaluate(root):
    plan=checked(root);done=E.read(root/'learning/completion.json');E.require(done['status']=='complete','training incomplete')
    source=Path(plan['source']);roles=E.read(source/'roles-private.json');start=time.monotonic()
    controls=[dict(root=str(root),arm='initial_control',seed=seed,sampling_seed=G.stream_seed('evaluation',i,0,0),
        checkpoint_sha256=E.sha(source/'learning/initial.pt'),reference=str(source/f'learning/evaluation/initial/{i}-0.json.gz'),
        output=str(root/f'evaluation/initial_control/{i}.json.gz')) for i,seed in enumerate(roles['evaluation'][:2])]
    control_reports=[]
    for job in controls:
        report=evaluation_worker(job);E.require(report['status']!='fault','initial evaluation control failed: '+str(report))
        control_reports.append(report)
    jobs=[dict(root=str(root),arm=arm,seed=seed,sampling_seed=G.stream_seed('evaluation',i,0,0),
        checkpoint_sha256=done['reports'][arm]['checkpoint_sha256'],output=str(root/f'evaluation/{arm}/{i}.json.gz'))
        for i,seed in enumerate(roles['evaluation']) for arm in ARMS]
    reports=[]
    with ProcessPoolExecutor(max_workers=plan['workers'],mp_context=multiprocessing.get_context('spawn')) as executor:
        for report in executor.map(evaluation_worker,jobs,chunksize=1):
            reports.append(report)
            E.require(time.monotonic()-start < plan['evaluation_seconds'],'evaluation time budget reached')
            put(root/'status.json',dict(status='evaluating',complete=len(reports),assigned=len(jobs),
                faults=sum(r['status']=='fault' for r in reports),seconds=time.monotonic()-start))
            if len(reports)%32==0:print(dict(complete=len(reports),assigned=len(jobs)),flush=True)
    faults=[r for r in reports if r['status']=='fault']
    if faults:
        put(root/'result.json',dict(status='incomplete_faults',faults=faults,assigned=len(jobs)));return
    x=G.C.D.runtime(plan['runtime'])
    refs={r['seed']:r for r in E.read(Path(E.read(source/'protocol.json')['natural_source'])/'fit-references.json')}
    byarm={arm:[int(E.read(root/f'evaluation/{arm}/{i}.json.gz')['status']=='heart_win') for i in range(128)] for arm in ARMS}
    parent=[int(refs[seed]['status']=='heart_win') for seed in roles['evaluation']]
    comparisons={arm:dict(grouped=x.B.paired_counts(byarm['grouped'],byarm[arm]),
                           parent=x.B.paired_counts(parent,byarm[arm])) for arm in ('state_mc','temporal')}
    temporal_extra=x.B.paired_counts(byarm['state_mc'],byarm['temporal'])
    qualified=[arm for arm,rows in comparisons.items() if all(r['net_gain']>=8 and r['exact_p']<.025 for r in rows.values())]
    report=dict(status='complete',wins={k:sum(v) for k,v in byarm.items()},parent_wins=sum(parent),families=128,
        comparisons=comparisons,temporal_vs_state=temporal_extra,qualified=qualified,
        temporal_mechanism_gate='temporal' in qualified and temporal_extra['net_gain']>=4,
        new_base_games=386,winner_replans=sum(bool(r['winner_replanned']) for r in reports+control_reports),faults=0,
        unseen_acceptance_games=0,policy_adoption=False,seconds=time.monotonic()-start,
        limits='One first-update comparison on historical development families, not complete actor-critic training or untouched generalization.')
    put(root/'result.json',report);put(root/'status.json',dict(status='complete'));print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','train','evaluate'))
    p.add_argument('--root',required=True,type=Path);p.add_argument('--source',type=Path);p.add_argument('--baseline',type=Path)
    args=p.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.source.resolve(),args.baseline.resolve())
    elif args.command=='train':train(root)
    else:evaluate(root)
