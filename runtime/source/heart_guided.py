#!/usr/bin/env python3
"""Learn terminal-backed corrections to a frozen public-state heuristic prior."""
import argparse
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


class GuidedScorer(H.A.Scorer):
    model_type = "heuristic_residual"
    def __init__(self, arch=(128,128), prior_strength=3.0):
        super().__init__(arch)
        self.prior_strength=prior_strength

    def with_prior(self, logits, teacher):
        prior=H.torch.zeros_like(logits)
        prior[teacher]=self.prior_strength
        return logits+prior

    def residual_logits(self, values):
        return self.net(values).squeeze(-1)

    def choose(self, gc, observation, actions, descriptors):
        teacher=R.heuristic_choice(gc,actions,descriptors)
        logits=self.score(H.torch.tensor(observation),descriptors)
        return int(self.with_prior(logits,teacher).argmax())


class SemanticScorer(GuidedScorer):
    """Share corrections across runs instead of recognizing a full map/deck fingerprint."""
    model_type = "semantic_residual"
    scalar_indices = (0,1,2,3,4,8,9,10,11,32,33,34)

    def __init__(self, arch=(64,), prior_strength=3.0):
        H.torch.nn.Module.__init__(self)
        self.prior_strength=prior_strength
        self.feature_dim=H.A.DESC_DIM+H.A.W_ACTION*(len(self.scalar_indices)+4)+H.A.W_CARD*4
        layers=[];previous=self.feature_dim
        for width in arch:
            layers.extend([H.torch.nn.Linear(previous,width),H.torch.nn.ReLU()]);previous=width
        layers.append(H.torch.nn.Linear(previous,1));self.net=H.torch.nn.Sequential(*layers)

    def features(self, values):
        desc=values[:,H.A.OBS_DIM:]
        kinds=desc[:,H.A.OFF_ACTION:H.A.OFF_ACTION+H.A.W_ACTION]
        scalars=values[:,self.scalar_indices]
        acts=H.F.one_hot((values[:,4]*4).long().clamp(1,4)-1,4).to(values.dtype)
        cards=desc[:,H.A.OFF_CARD:H.A.OFF_CARD+H.A.W_CARD]
        return H.torch.cat([desc,(kinds[:,:,None]*scalars[:,None,:]).flatten(1),
            (kinds[:,:,None]*acts[:,None,:]).flatten(1),(cards[:,:,None]*acts[:,None,:]).flatten(1)],dim=1)

    def residual_logits(self,values):return self.net(self.features(values)).squeeze(-1)

    def score(self,observation,descriptors):
        rows=H.torch.stack([H.torch.cat([observation,H.torch.tensor(d,dtype=H.torch.float32)]) for d in descriptors])
        return self.residual_logits(rows)


class DeckScorer(SemanticScorer):
    """Condition shared candidate scores on the public deck, relics, and potions."""
    model_type = "deck_residual"

    def __init__(self,arch=(192,),prior_strength=3.0):
        H.torch.nn.Module.__init__(self)
        self.prior_strength=prior_strength
        # NNInterface's tail is: card counts/upgrades/misc, two 16-slot
        # special-card arrays, bottled cards, relic presence/data, potion slots.
        self.deck_offset=H.A.BASE_OBS_DIM-(6*H.A.CARD_CAP+32+2*H.A.RELIC_CAP+5*H.A.POTION_CAP)
        if set(H.A._maxes[self.deck_offset:self.deck_offset+2*H.A.CARD_CAP])!={20.0}:
            raise ValueError('public deck observation layout changed')
        self.semantic_dim=H.A.DESC_DIM+H.A.W_ACTION*(len(self.scalar_indices)+4)+H.A.W_CARD*4
        self.feature_dim=self.semantic_dim+H.A.BASE_OBS_DIM-self.deck_offset
        layers=[];previous=self.feature_dim
        for width in arch:
            layers.extend([H.torch.nn.Linear(previous,width),H.torch.nn.ReLU()]);previous=width
        layers.append(H.torch.nn.Linear(previous,1));self.net=H.torch.nn.Sequential(*layers)

    def features(self,values):
        return H.torch.cat([super().features(values),values[:,self.deck_offset:H.A.BASE_OBS_DIM]],dim=1)


class CardContextScorer(DeckScorer):
    """Expose candidate ownership and card types as shared, derived public facts."""
    model_type = "card_context_residual"

    def __init__(self,arch=(192,),prior_strength=3.0):
        super().__init__(arch,prior_strength)
        self.context_offset=self.feature_dim
        self.feature_dim+=14
        self.net[0]=H.torch.nn.Linear(self.feature_dim,arch[0])
        types=(R.sts.CardType.ATTACK,R.sts.CardType.SKILL,R.sts.CardType.POWER,
               R.sts.CardType.STATUS,R.sts.CardType.CURSE)
        cards=[R.sts.Card(R.sts.CardId(i)) for i in range(H.A.CARD_CAP)]
        self.register_buffer('card_types',H.torch.tensor([[float(c.type==t) for t in types] for c in cards]))
        self.register_buffer('nonstarter_attacks',H.torch.tensor([
            float(c.type==R.sts.CardType.ATTACK and not c.is_starter_strike_or_defend) for c in cards]))

    def features(self,values):
        base=super().features(values)
        desc=values[:,H.A.OBS_DIM:]
        candidates=desc[:,H.A.OFF_CARD:H.A.OFF_CARD+H.A.W_CARD]
        faces=values[:,self.deck_offset:self.deck_offset+2*H.A.CARD_CAP].reshape(-1,H.A.CARD_CAP,2)*20.0
        counts=faces.sum(dim=2)
        owned=(candidates*counts).sum(dim=1,keepdim=True)
        upgraded_owned=(candidates*faces[:,:,1]).sum(dim=1,keepdim=True)
        candidate_types=candidates@self.card_types
        deck_types=(counts@self.card_types)/10.0
        nonstarter=(counts@self.nonstarter_attacks[:,None])/10.0
        upgrade=desc[:,H.A.OFF_CARD_UPGRADE:H.A.OFF_CARD_UPGRADE+1]*H.A.SPECIAL_SCALE
        return H.torch.cat([base,owned,upgraded_owned,candidate_types,deck_types,nonstarter,upgrade],dim=1)


def losses(net,groups):
    values,lengths=H.matrix(groups)
    scores=net.residual_logits(values).split(lengths)
    adjusted=[net.with_prior(logits,g['teacher']) for logits,g in zip(scores,groups)]
    return H.torch.stack([H.F.cross_entropy(score.unsqueeze(0),H.torch.tensor([g['chosen']]))
                         for score,g in zip(adjusted,groups)]),adjusted


def metrics(net,groups):
    net.eval();correct=0;loss_total=0.0
    with H.torch.no_grad():
        for start in range(0,len(groups),64):
            batch=groups[start:start+64];ls,scores=losses(net,batch)
            loss_total+=float(ls.sum())
            correct+=sum(int(s.argmax())==g['chosen'] for s,g in zip(scores,batch))
    return {'groups':len(groups),'correct':correct,'agreement':correct/len(groups),
            'loss':loss_total/len(groups)}


def key(group):return H.digest([group['seed'],group['observation'],group['descriptors']])


def sample_epoch(data,config,rng):
    """Keep stratum sizes and optimizer budget fixed when expanding seed coverage."""
    groups=rng.sample(data['warm'],min(config['broad_samples_per_epoch'],len(data['warm'])))
    for name,repeats in (('success','success_repeats'),('improved','improvement_repeats')):
        values=data[name]
        count=config.get(name+'_samples_per_epoch',len(values)*config[repeats])
        if not values:
            if count:raise ValueError('cannot sample a missing training stratum')
            continue
        whole,remainder=divmod(count,len(values))
        groups+=values*whole
        if remainder:groups+=rng.sample(values,remainder)
    rng.shuffle(groups)
    return groups


def launch(parent,legacy,output):
    parent,legacy,directory=map(lambda p:Path(p).resolve(),(parent,legacy,output))
    for p in (parent,legacy):
        for name,expected in H.read_json(p/'manifest.json')['frozen_files'].items():
            if hashlib.sha256((p/name).read_bytes()).hexdigest()!=expected:raise ValueError('source changed '+name)
    directory.mkdir(parents=True,exist_ok=False)
    seeds=H.read_json(parent/'seeds.json');data={}
    for split in ('train','validation'):
        warm=H.read_json(parent/f'data/{split}-warm.json.gz')
        successful=H.read_json(parent/f'data/{split}-success.json.gz')
        rows={(g['seed'],g['fingerprint']):g for g in warm+successful}
        branch_runs=[H.read_json(p) for p in sorted((legacy/f'branches/{split}').glob('*.json.gz'))]
        branches=H.usable_groups(branch_runs)
        branch_by_state={(g['seed'],g['fingerprint']):g for g in branches}
        overrides={}
        for path in (legacy/f'branches/{split}/successes').glob('*.json.gz'):
            run=H.read_json(path)
            identity=(run['seed'],run['discovery_root'])
            overrides[identity]=branch_by_state[identity]['chosen']
        positives=[{**g,'teacher':overrides.get((g['seed'],g['fingerprint']),g['chosen'])} for g in successful]
        seen={key(g) for g in positives}
        # Keep full-route labels when several winning alternatives share a state.
        for branch in branches:
            if branch['targets'][branch['chosen']]==0.0 and 1.0 in branch['targets']:
                state=rows.get((branch['seed'],branch['fingerprint']))
                if state is None:
                    if split=='train':raise ValueError('missing encoded improvement state')
                    continue
                if key(state) not in seen:
                    positives.append({**state,'teacher':branch['chosen'],'chosen':branch['targets'].index(1.0)})
                    seen.add(key(state))
        broad=[{**g,'teacher':g['chosen']} for g in warm if key(g) not in seen]
        improved=[g for g in positives if g['teacher']!=g['chosen']]
        if not {g['seed'] for g in broad+positives}<=set(seeds[split]):raise ValueError('seed role violation')
        for name,groups in (('warm',broad),('success',positives),('improved',improved)):
            H.write_json(directory/f'data/{split}-{name}.json.gz',groups)
        data[split]={'warm_groups':len(broad),'winning_groups':len(positives),'improved_groups':len(improved),
                     'winning_seeds':sorted({g['seed'] for g in successful})}
    shutil.copytree(parent/'engine',directory/'engine');(directory/'source').mkdir()
    for name in ('armG_train.py','heart_runtime.py','heart_train.py','heart_guided.py'):
        shutil.copy2(Path(__file__).parent/name,directory/'source'/name)
    initial=H.torch.load(parent/'models/last.pt',weights_only=True,map_location='cpu')
    net=GuidedScorer(tuple(initial['arch']),3.0);net.load_state_dict(initial['state_dict'])
    H.torch.nn.init.zeros_(net.net[-1].weight);H.torch.nn.init.zeros_(net.net[-1].bias)
    H.torch.save({'state_dict':net.state_dict(),'arch':initial['arch'],'model_type':'heuristic_residual',
                  'prior_strength':3.0},directory/'initial.pt')
    config={**H.read_json(parent/'config.json'),'guided_epochs':32,'improvement_repeats':128,
            'success_repeats':2,'broad_samples_per_epoch':8192,'learning_rate':0.0001,'prior_strength':3.0}
    H.write_json(directory/'config.json',config);H.write_json(directory/'seeds.json',seeds)
    frozen={str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}
    H.write_json(directory/'manifest.json',{'frozen_files':frozen,'data':data,'parent':str(parent),
        'legacy_data':str(legacy),'method':'frozen heuristic prior plus learned terminal-guided residual',
        'prior_policy':R.POLICY_VERSION,'gate':'natural training and validation Heart win before fresh acceptance'})
    env={**os.environ,'STS_LIGHTSPEED_BUILD':str(directory/'engine'),'ASC':'20','OMP_NUM_THREADS':'1',
         'OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    with (directory/'stdout.log').open('ab') as log:
        child=subprocess.Popen([sys.executable,str(directory/'source/heart_guided.py'),'run',str(directory)],
            cwd=directory,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    H.write_json(directory/'launch.json',{'pid':child.pid,'directory':str(directory)})
    print(json.dumps({'pid':child.pid,'data':data}))


def experiment(directory):
    directory=Path(directory).resolve();manifest=H.read_json(directory/'manifest.json')
    for name,expected in manifest['frozen_files'].items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=expected:raise ValueError('frozen input changed '+name)
    config=H.read_json(directory/'config.json');seeds=H.read_json(directory/'seeds.json')
    data={s:{k:H.read_json(directory/f'data/{s}-{k}.json.gz') for k in ('warm','success','improved')}
          for s in ('train','validation')}
    if {g['seed'] for v in data['train'].values() for g in v}&{g['seed'] for v in data['validation'].values() for g in v}:
        raise ValueError('training and validation overlap')
    H.torch.set_num_threads(1);H.torch.manual_seed(config['model_seed'])
    net=H.load_scorer(H.torch.load(directory/'initial.pt',weights_only=True,map_location='cpu'))
    optimizer=H.torch.optim.AdamW(net.parameters(),lr=config['learning_rate'],weight_decay=config['weight_decay'])
    rng=random.Random(config['model_seed']);updates=0;best=None;best_qualified=None;started=time.monotonic()
    (directory/'models').mkdir()
    report={'status':'training','method':net.model_type,'prior_strength':net.prior_strength,
        'initial':{s:metrics(net,data[s]['success']) for s in data},'data':manifest['data'],'evaluations':[],
        'fresh_acceptance_used':False}
    H.write_json(directory/'report.json',report)
    for epoch in range(1,config['guided_epochs']+1):
        groups=sample_epoch(data['train'],config,rng);net.train()
        for start in range(0,len(groups),config['batch_groups']):
            ls,_=losses(net,groups[start:start+config['batch_groups']]);loss=ls.mean()
            if not H.torch.isfinite(loss):raise RuntimeError('nonfinite loss')
            optimizer.zero_grad();loss.backward();H.torch.nn.utils.clip_grad_norm_(net.parameters(),1.0,error_if_nonfinite=True)
            optimizer.step();updates+=1
        scores={s:metrics(net,data[s]['success']) for s in data}
        H.append_metric(directory,{'stage':'fit','epoch':epoch,'updates':updates,'success_trajectory':scores})
        H.write_json(directory/'status.json',{'stage':'fit','epoch':epoch,'agreement':{s:scores[s]['agreement'] for s in scores}})
        checkpoint={'state_dict':net.state_dict(),'arch':config['arch'],'model_type':net.model_type,
                    'prior_strength':net.prior_strength,'epoch':epoch,'updates':updates,'ascension':20,
                    'input_dim':H.A.INPUT_DIM,'observation_dim':H.A.OBS_DIM,'candidate_dim':H.A.DESC_DIM,
                    'state_hash':H.state_hash(net),'prior_policy':R.POLICY_VERSION}
        H.torch.save({**checkpoint,'optimizer':optimizer.state_dict()},directory/'models/last.pt')
        if epoch%config['evaluation_interval']:continue
        path=directory/f'models/epoch-{epoch}.pt';H.torch.save(checkpoint,path)
        outcome={'epoch':epoch,'checkpoint':str(path),'success_trajectory':scores}
        for split in data:
            selected=manifest['data'][split]['winning_seeds']
            if split=='validation':selected=list(dict.fromkeys(selected+config.get('validation_probe_seeds',[])+seeds['validation'][:config['validation_natural_count']]))
            jobs=[{'mode':'evaluate','seed':seed,'checkpoint':str(path),
                   'output':str(directory/f'evaluate/epoch-{epoch}/{split}/{seed}.json.gz')} for seed in selected]
            runs=H.run_jobs(directory,jobs,config,f'epoch_{epoch}_{split}',time.monotonic()+600)
            summary=H.summarize(runs)
            outcome[split]={**summary,'requested':len(jobs),
                'completed_valid':summary['runs']==len(jobs) and summary['valid_terminal']==len(jobs),
                'winning_seeds':[r['seed'] for r in runs if r.get('status')=='heart_win']}
        score=(outcome['validation']['heart_wins'],scores['validation']['agreement'],-scores['validation']['loss'])
        if best is None or score>best:best=score;report['best']=outcome;shutil.copy2(path,directory/'models/policy.pt')
        report['evaluations'].append(outcome);H.write_json(directory/'report.json',report)
        H.append_metric(directory,{'stage':'natural_validation','epoch':epoch,
            'train_wins':outcome['train']['heart_wins'],'validation_wins':outcome['validation']['heart_wins']})
        if (all(outcome[s]['completed_valid'] for s in data)
                and outcome['train']['heart_wins']>=config.get('minimum_train_wins',1)
                and outcome['validation']['heart_wins']>=config.get('minimum_validation_wins',1)):
            report['gate_passed']=True
            if best_qualified is None or score>best_qualified:
                best_qualified=score;report['best_qualified']=outcome
            if not config.get('complete_training_budget',False):break
    if report.get('gate_passed'):
        report['best']=report['best_qualified']
        shutil.copy2(report['best']['checkpoint'],directory/'models/policy.pt')
    report.update(status='ready_for_fresh_seed_acceptance' if report.get('gate_passed') else 'needs_training_improvement',
                  elapsed_seconds=time.monotonic()-started,updates=updates)
    H.write_json(directory/'report.json',report);H.write_json(directory/'status.json',{'stage':'finished','status':report['status']})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    start=sub.add_parser('launch');start.add_argument('parent');start.add_argument('legacy');start.add_argument('output')
    run=sub.add_parser('run');run.add_argument('directory');args=parser.parse_args()
    if args.command=='launch':launch(args.parent,args.legacy,args.output)
    else:experiment(args.directory)
