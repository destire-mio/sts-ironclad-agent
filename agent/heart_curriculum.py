#!/usr/bin/env python3
"""Train complete successful routes with broad imitation, then gate on full runs."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

import heart_train as H
import heart_runtime as R


def identity(group):
    return H.digest([group['seed'], group['observation'], group['descriptors']])


def prepare(parent, source_data, directory):
    parent, source_data, directory = map(lambda p: Path(p).resolve(), (parent, source_data, directory))
    if (directory / 'manifest.json').exists():
        raise ValueError('experiment already frozen')
    directory.mkdir(parents=True, exist_ok=True)
    for p in (parent, source_data):
        for name, expected in H.read_json(p / 'manifest.json')['frozen_files'].items():
            if hashlib.sha256((p/name).read_bytes()).hexdigest() != expected:
                raise ValueError('source input changed: '+name)
    seeds = H.read_json(parent/'seeds.json')
    lineage, data = [], {}
    for split, count in (('train', len(seeds['train'])), ('validation', 128)):
        wins_path = directory / f'{split}-winning-samples.json.gz'
        winning = H.read_json(wins_path)
        if not {g['seed'] for g in winning} <= set(seeds[split]):
            raise ValueError('successful trajectory has wrong seed role')
        overrides = {identity(g) for g in winning}
        warm = []
        for seed in seeds[split][:count]:
            path = source_data / f'prefix/{split}/{seed}.json.gz'
            run = H.read_json(path)
            if run['seed'] != seed or R.target(run['status']) is None:
                raise ValueError('invalid natural training prefix')
            warm.extend(g for g in run['samples'] if identity(g) not in overrides)
            lineage.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'split':split})
        # Winning full-route actions override old teacher actions on the same input.
        H.write_json(directory / f'data/{split}-warm.json.gz', warm)
        H.write_json(directory / f'data/{split}-success.json.gz', winning)
        data[split] = {'warm_groups':len(warm),'winning_groups':len(winning),
                       'warm_seeds':len({g['seed'] for g in warm}),
                       'winning_seeds':sorted({g['seed'] for g in winning})}
    shutil.copytree(parent/'engine', directory/'engine')
    (directory/'source').mkdir()
    for name in ('heart_train.py','heart_runtime.py','armG_train.py'):
        shutil.copy2(parent/'source'/name,directory/'source'/name)
    shutil.copy2(__file__,directory/'source/heart_curriculum.py')
    shutil.copy2(parent/'small/models/policy.pt',directory/'initial.pt')
    config = {**H.read_json(parent/'config.json'), 'arch':[128,128], 'curriculum_epochs':24,
              'broad_samples_per_epoch':12288, 'success_repeats':8, 'batch_groups':64,
              'learning_rate':0.0001, 'weight_decay':0.00001, 'evaluation_interval':4,
              'policy_start_floor':0, 'workers':8, 'validation_natural_count':64}
    H.write_json(directory/'config.json',config)
    H.write_json(directory/'seeds.json',seeds)
    H.write_json(directory/'data-lineage.json',lineage)
    frozen = {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in directory.rglob('*') if p.is_file() and p.name != 'diagnostic.json'}
    H.write_json(directory/'manifest.json',{'frozen_files':frozen,'parent':str(parent),
        'source_data':str(source_data),'data':data,'training_signal':'terminal-success self-imitation plus broad teacher imitation',
        'gate':'at least one training and one validation natural Heart win before fresh random acceptance'})
    env = {**os.environ,'STS_LIGHTSPEED_BUILD':str(directory/'engine'),'ASC':'20',
           'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    with (directory/'stdout.log').open('ab') as log:
        child=subprocess.Popen([sys.executable,str(directory/'source/heart_curriculum.py'),'run',str(directory)],
            cwd=directory,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    H.write_json(directory/'launch.json',{'pid':child.pid,'directory':str(directory)})
    print(json.dumps({'pid':child.pid,'data':data}))


def trajectory_metrics(net, groups):
    net.eval()
    counts, correct, total = Counter(), Counter(), Counter()
    with H.torch.no_grad():
        for start in range(0,len(groups),64):
            batch=groups[start:start+64]
            losses, scores=H.group_losses(net,batch,'bootstrap')
            for g, loss, logits in zip(batch,losses,scores):
                selected=int(logits.argmax())
                # Equal descriptor rows are indistinguishable to this network.
                match=g['descriptors'][selected] == g['descriptors'][g['chosen']]
                correct[g['seed']]+=int(match)
                total[g['seed']]+=1
                counts[g['seed']]+=float(loss)
    return {'agreement':sum(correct.values())/sum(total.values()),
            'loss':sum(counts.values())/sum(total.values()),
            'by_seed':{str(seed):{'correct':correct[seed],'total':total[seed]} for seed in total}}


def experiment(directory):
    directory=Path(directory).resolve()
    manifest=H.read_json(directory/'manifest.json')
    for name,expected in manifest['frozen_files'].items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('frozen input changed: '+name)
    config=H.read_json(directory/'config.json');seeds=H.read_json(directory/'seeds.json')
    data={split:{kind:H.read_json(directory/f'data/{split}-{kind}.json.gz')
                 for kind in ('warm','success')} for split in ('train','validation')}
    if {g['seed'] for v in data['train'].values() for g in v} & {g['seed'] for v in data['validation'].values() for g in v}:
        raise ValueError('training/validation leakage')
    H.torch.set_num_threads(1);H.torch.manual_seed(config['model_seed'])
    net=H.A.Scorer(tuple(config['arch']))
    net.load_state_dict(H.torch.load(directory/'initial.pt',weights_only=True,map_location='cpu')['state_dict'])
    optimizer=H.torch.optim.AdamW(net.parameters(),lr=config['learning_rate'],weight_decay=config['weight_decay'])
    rng=random.Random(config['model_seed']);updates=0;best=None
    (directory/'models').mkdir(exist_ok=True)
    report={'status':'training','data':manifest['data'],'evaluations':[],
            'initial':{s:trajectory_metrics(net,data[s]['success']) for s in data},'fresh_acceptance_used':False}
    H.write_json(directory/'report.json',report)
    started=time.monotonic()
    for epoch in range(1,config['curriculum_epochs']+1):
        broad=rng.sample(data['train']['warm'],min(config['broad_samples_per_epoch'],len(data['train']['warm'])))
        groups=broad+data['train']['success']*config['success_repeats']
        rng.shuffle(groups);net.train()
        for start in range(0,len(groups),config['batch_groups']):
            losses,_=H.group_losses(net,groups[start:start+config['batch_groups']],'bootstrap')
            loss=losses.mean()
            if not H.torch.isfinite(loss): raise RuntimeError('nonfinite loss')
            optimizer.zero_grad();loss.backward()
            H.torch.nn.utils.clip_grad_norm_(net.parameters(),1.0,error_if_nonfinite=True)
            optimizer.step();updates+=1
        scores={split:trajectory_metrics(net,data[split]['success']) for split in data}
        H.append_metric(directory,{'stage':'fit','epoch':epoch,'updates':updates,'success_trajectory':scores})
        H.write_json(directory/'status.json',{'stage':'fit','epoch':epoch,'updates':updates,'agreement':{s:scores[s]['agreement'] for s in scores}})
        checkpoint={'state_dict':net.state_dict(),'arch':config['arch'],'stage':'full_success_self_imitation',
                    'epoch':epoch,'updates':updates,'ascension':20,'state_hash':H.state_hash(net),'success_trajectory':scores}
        H.torch.save({**checkpoint,'optimizer':optimizer.state_dict()},directory/'models/last.pt')
        if epoch % config['evaluation_interval']:
            continue
        path=directory/f'models/epoch-{epoch}.pt';H.torch.save(checkpoint,path)
        outcome={'epoch':epoch,'success_trajectory':scores,'checkpoint':str(path)}
        for split in ('train','validation'):
            selected=manifest['data'][split]['winning_seeds']
            if split=='validation': selected=list(dict.fromkeys(selected+seeds['validation'][:config['validation_natural_count']]))
            jobs=[{'mode':'evaluate','seed':seed,'checkpoint':str(path),
                   'output':str(directory/f'evaluate/epoch-{epoch}/{split}/{seed}.json.gz')} for seed in selected]
            runs=H.run_jobs(directory,jobs,config,f'epoch_{epoch}_{split}',time.monotonic()+600)
            outcome[split]=H.summarize(runs)
            outcome[split]['heart_wins']=sum(r.get('status')=='heart_win' for r in runs)
            outcome[split]['winning_seeds']=[r['seed'] for r in runs if r.get('status')=='heart_win']
        score=(outcome['validation']['heart_wins'],scores['validation']['agreement'],-scores['validation']['loss'])
        if best is None or score>best:
            best=score;shutil.copy2(path,directory/'models/policy.pt');report['best']=outcome
        report['evaluations'].append(outcome)
        H.write_json(directory/'report.json',report)
        H.append_metric(directory,{'stage':'natural_validation','epoch':epoch,
            'train_wins':outcome['train']['heart_wins'],'validation_wins':outcome['validation']['heart_wins']})
        if outcome['train']['heart_wins'] and outcome['validation']['heart_wins']:
            report['gate_passed']=True
            shutil.copy2(path,directory/'models/policy.pt')
            report['best']=outcome
            break
    report.update(status='ready_for_fresh_seed_acceptance' if report.get('gate_passed') else 'needs_training_improvement',
                  elapsed_seconds=time.monotonic()-started,updates=updates)
    H.write_json(directory/'report.json',report)
    H.write_json(directory/'status.json',{'stage':'finished','status':report['status']})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    launch=sub.add_parser('launch');launch.add_argument('parent');launch.add_argument('data');launch.add_argument('directory')
    run=sub.add_parser('run');run.add_argument('directory')
    args=parser.parse_args()
    if args.command=='launch':prepare(args.parent,args.data,args.directory)
    else:experiment(args.directory)
