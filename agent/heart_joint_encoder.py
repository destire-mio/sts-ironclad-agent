"""Train a joint-decision encoder copy without changing the continuation policy.

Both arms share full-batch terminal-tree optimization and initial tensors.
Only the dedicated encoder copy can learn in the trainable arm. Original
nonintervention/fallback decisions always use the untouched parent module.
"""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import torch
from torch import nn

import heart_early_card_scope as E

RECIPE = dict(steps=1000, checkpoints=[0,100,250,500,1000], head_learning_rate=.03,
              encoder_learning_rate=.00003, l2=.001, gradient_norm=1., dtype='float64',
              inner_namespace='E182-joint-inner:', inner_modulus=5)
ARMS = ('frozen','trainable')


def components(runtime):
    x=E.load_runtime(runtime)
    spec=importlib.util.spec_from_file_location('e182_packing',Path(__file__).with_name('heart_relic_card_training.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    E.require(Path(helper.R.sts.__file__).resolve()==Path(x.R.sts.__file__).resolve(),'packing runtime differs')
    return x,helper


class Head(nn.Module):
    def __init__(self,count,width=192):
        super().__init__()
        self.weight=nn.Parameter(torch.zeros(width,dtype=torch.float64))
        self.static_scores=nn.Parameter(torch.zeros(count,dtype=torch.float64))
        self.register_buffer('scale',torch.ones(width,dtype=torch.float64))

    def forward(self,encoded,group):
        mask=group['mask']; mean=(encoded*mask[:,:,None]).sum(1)/mask.sum(1)[:,None]
        scores=((encoded-mean[:,None,:])/self.scale)@self.weight+self.static_scores[group['positions']]
        scores=scores+nn.functional.one_hot(group['baseline'],scores.shape[1]).to(scores.dtype)
        scores=scores.masked_fill(~mask,float('-inf'))
        fallback=torch.full_like(scores,float('-inf'));fallback.scatter_(1,group['baseline'][:,None],0.)
        return torch.where(group['allowed'][:,None],scores,fallback)


class JointEncoderPolicy(nn.Module):
    model_type='joint_encoder_copy'

    def __init__(self,x,support,arm,checkpoint=None):
        super().__init__();self.x=x;self.arm=arm;self.base=E.parent_model(x)
        E.require(arm in ARMS,'unknown learning arm')
        E.require(set(support)=={'relic','card'} and all(v and len(v)==len(set(v)) for v in support.values()),
                  'empty, duplicate or missing option support')
        self.base.requires_grad_(False)
        old=self.base.base
        E.require(old.model_type=='card_context_residual' and len(old.net)==3 and old.net[0].out_features==192,
                  'unsupported encoder layout')
        self.encoder_weight=nn.Parameter(old.net[0].weight.detach().double().clone(),requires_grad=arm=='trainable')
        self.encoder_bias=nn.Parameter(old.net[0].bias.detach().double().clone(),requires_grad=arm=='trainable')
        self.register_buffer('initial_weight',self.encoder_weight.detach().clone())
        self.register_buffer('initial_bias',self.encoder_bias.detach().clone())
        self.support={k:tuple(v) for k,v in support.items()}
        self.heads=nn.ModuleDict({k:Head(len(v)) for k,v in support.items()})
        if checkpoint:
            self.encoder_weight.data.copy_(checkpoint['encoder_weight'])
            self.encoder_bias.data.copy_(checkpoint['encoder_bias'])
            self.heads.load_state_dict(checkpoint['heads'])
        E.require(all(bool(torch.isfinite(value).all()) for value in self.learned_state()['heads'].values()),
                  'nonfinite learned head')
        E.require(all(bool((head.scale>0).all()) for head in self.heads.values()),'invalid fit scale')
        E.require(bool(torch.isfinite(self.encoder_weight).all() and torch.isfinite(self.encoder_bias).all()),
                  'nonfinite encoder copy')

    def features(self,observation,descriptors):
        rows=torch.cat((observation,descriptors),-1).float()
        # These are the frozen original feature transformations, including
        # public inventory counts and current candidate properties. Only the
        # copied linear layer below is trainable.
        return self.base.base.features(rows).double()

    def encode(self,features):
        projected=(torch.sparse.mm(features,self.encoder_weight.T) if features.is_sparse
                   else nn.functional.linear(features,self.encoder_weight))
        return (projected+self.encoder_bias).relu()

    def training_logits(self,data):
        results=[]
        for stage in ('relic','card'):
            group=data[stage];encoded=self.encode(group['encoder_features'])
            padded=torch.zeros((*group['mask'].shape,192),dtype=torch.float64)
            padded[group['mask']]=encoded
            results.append(self.heads[stage](padded,group))
        return results

    @torch.no_grad()
    def fit_scales(self,data):
        for stage in ('relic','card'):
            group=data[stage];encoded=self.encode(group['encoder_features'])
            padded=torch.zeros((*group['mask'].shape,192),dtype=torch.float64);padded[group['mask']]=encoded
            mean=(padded*group['mask'][:,:,None]).sum(1)/group['mask'].sum(1)[:,None]
            centered=(padded-mean[:,None,:])[group['mask']]
            self.heads[stage].scale.copy_(centered.square().mean(0).sqrt().clamp_min(.01))

    def learned_state(self):
        return dict(encoder_weight=self.encoder_weight.detach().clone(),encoder_bias=self.encoder_bias.detach().clone(),
                    heads={k:v.detach().clone() for k,v in self.heads.state_dict().items()})

    @torch.no_grad()
    def choose(self,gc,observation,actions,descriptors):
        parent=self.base.choose(gc,observation,actions,descriptors);J=self.x.J
        stage=('relic' if J.relic_eligible(gc,descriptors,parent) else
               'card' if J.card_eligible(gc,descriptors,parent) else None)
        if stage is None:return parent
        identifier=J.relic_option if stage=='relic' else J.card_option
        options=[i for i,d in enumerate(descriptors) if identifier(d) is not None]
        positions={v:i for i,v in enumerate(self.support[stage])}
        if any(identifier(descriptors[i]) not in positions for i in options):return parent
        group=dict(mask=torch.ones((1,len(options)),dtype=torch.bool),allowed=torch.ones(1,dtype=torch.bool),
            baseline=torch.tensor([options.index(parent)]),
            positions=torch.tensor([[positions[identifier(descriptors[i])] for i in options]]))
        values=self.features(torch.tensor([observation]*len(options)),torch.tensor([descriptors[i] for i in options]))
        scores=self.heads[stage](self.encode(values)[None],group)[0].tolist()
        return options[choose_index(scores,group['baseline'][0].item())]


def choose_index(scores,parent):
    best=max(scores);tied=[i for i,s in enumerate(scores) if best-s<=1e-9]
    return parent if parent in tied else min(tied)


def select_steps(curve,baseline_wins):
    selected=min(curve,key=lambda row:(-row['validation_wins'],row['validation_changes'],row['step']))
    return selected['step'] if selected['validation_wins']>baseline_wins else 0


def add_features(policy,data):
    for stage in ('relic','card'):
        observations=[];descriptors=[];indices=[];values=[];offset=0
        def flush():
            nonlocal offset
            if not observations:return
            with torch.no_grad():
                matrix=policy.features(torch.tensor(observations),torch.tensor(descriptors))
            at=matrix.nonzero().T;value=matrix[at[0],at[1]]
            at[0]+=offset;indices.append(at);values.append(value);offset+=len(matrix)
            observations.clear();descriptors.clear()
        for row in data[stage]['rows']:
            obs=policy.x.R.dense(row['observation'],policy.x.A.OBS_DIM)
            for candidate in row['candidates']:
                observations.append(obs);descriptors.append(policy.x.R.dense(row['descriptors'][candidate],policy.x.A.DESC_DIM))
                if len(observations)==256:flush()
        flush()
        data[stage]['encoder_features']=torch.sparse_coo_tensor(torch.cat(indices,1),torch.cat(values),
            (offset,policy.encoder_weight.shape[1]),check_invariants=True).coalesce()
        E.require(offset==int(data[stage]['mask'].sum()),'candidate feature alignment differs')


def pack(helper,bundle,references,support=None):
    seeds={r['seed'] for r in references};trees=[t for t in bundle['trees'] if t['seed'] in seeds]
    if support is None:
        rs,cs=helper.supports(trees,bundle['states']);support=dict(relic=rs,card=cs)
    data=helper.pack(trees,bundle['states'],bundle['labels'],references,support['relic'],support['card'],include_features=False)
    return data,support


def objective(policy,data):
    relic,card=policy.training_logits(data)
    result=policy.x.J.expected_returns(relic,card,data['labels'].double(),data['branch_indices'],data['terminals'].double())
    reward=(result.sum()+data['unchanged_wins'])/data['assigned']
    penalty=sum(p.square().sum() for p in policy.heads.parameters())
    if policy.arm=='trainable':
        penalty=penalty+(policy.encoder_weight-policy.initial_weight).square().sum()+(policy.encoder_bias-policy.initial_bias).square().sum()
    return -reward+RECIPE['l2']*penalty,reward


@torch.no_grad()
def outcomes(policy,data):
    rs,cs=policy.training_logits(data);card_choices=[]
    for scores,parent in zip(cs.tolist(),data['card']['baseline'].tolist()):card_choices.append(choose_index(scores,parent))
    result={r['seed']:int(r['status']=='heart_win') for r in data['references']};changes=0;choices=[]
    for i,tree in enumerate(data['trees']):
        ri=choose_index(rs[i].tolist(),int(data['relic']['baseline'][i]));ci=int(data['branch_indices'][i,ri])
        if ci<0:
            target=int(data['terminals'][i,ri]);card_changed=False;card_choice=None
        else:
            card_choice=card_choices[ci];target=int(data['labels'][ci,card_choice])
            card_changed=card_choice!=int(data['card']['baseline'][ci])
        changed=ri!=int(data['relic']['baseline'][i]) or card_changed
        changes+=changed;result[tree['seed']]=target
        choices.append(dict(seed=tree['seed'],relic=ri,card=card_choice,target=target,changed=changed))
    return dict(wins=sum(result.values()),changed=changes,targets=result,choices=choices)


def fit(policy,data,steps,checkpoint=None):
    policy.fit_scales(data)
    groups=[dict(params=list(policy.heads.parameters()),lr=RECIPE['head_learning_rate'])]
    if policy.arm=='trainable':groups.append(dict(params=[policy.encoder_weight,policy.encoder_bias],lr=RECIPE['encoder_learning_rate']))
    optimizer=torch.optim.Adam(groups);parameters=[p for p in policy.parameters() if p.requires_grad]
    if checkpoint:checkpoint(0,policy)
    for step in range(1,steps+1):
        loss,reward=objective(policy,data)
        E.require(bool(torch.isfinite(loss)),'nonfinite terminal-tree objective')
        optimizer.zero_grad();loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters,RECIPE['gradient_norm'],error_if_nonfinite=True);optimizer.step()
        if checkpoint and step in RECIPE['checkpoints']:checkpoint(step,policy)


def registered(root):
    reg=E.read(root/'registration.json')
    for path,digest in reg['hashes'].items():E.require(E.sha(path)==digest,'bound input changed: '+path)
    E.require(E.sha(__file__)==reg['runner_sha256'],'encoder runner changed')
    plan=E.read(root/'protocol.json')
    E.require(plan['recipe']==RECIPE and plan['new_games']==0 and plan['arms']==list(ARMS),'recipe changed')
    E.proof(root/'data','completion.json')
    for path,digest in E.read(root/'data/source-proofs.json').items():
        E.require(E.sha(path)==digest,'completed source proof changed: '+path)
    return plan


def train(root):
    plan=registered(root);x,helper=components(plan['runtime']);torch.set_num_threads(1)
    bundle=E.read(root/'data/bundle.json.gz');refs=[r for r in bundle['references'] if r['split']=='fit']
    roles=E.read(root/'data/roles-private.json')
    E.require(roles=={role:[r['seed'] for r in bundle['references'] if r['split']==role]
                     for role in ('fit','label_holdout')},'bundle family roles changed')
    E.require(len(set(sum(roles.values(),[])))==5632,'family roles overlap')
    E.require(x.identity==E.read(root/'data/report.json')['identity'],'source and continuation identities differ')
    E.require(len(refs)==4608,'assigned fit families changed')
    validation=[r for r in refs if int(hashlib.sha256((RECIPE['inner_namespace']+str(r['seed'])).encode()).hexdigest(),16)%RECIPE['inner_modulus']==0]
    valid_seeds={r['seed'] for r in validation};training=[r for r in refs if r['seed'] not in valid_seeds]
    inner,support=pack(helper,bundle,training);valid,_=pack(helper,bundle,validation,support)
    full,full_support=pack(helper,bundle,refs)
    for data,s in ((inner,support),(valid,support),(full,full_support)):add_features(JointEncoderPolicy(x,s,'frozen'),data)
    out=root/'learning';out.mkdir();reports=[]
    E.write(out/'roles.json',dict(fit=[r['seed'] for r in refs],inner_train=[r['seed'] for r in training],
        inner_validation=sorted(valid_seeds),inner_support=support,full_support=full_support))
    baseline_valid=sum(r['status']=='heart_win' for r in validation)
    for arm in ARMS:
        directory=out/arm;directory.mkdir();curve=[];policy=JointEncoderPolicy(x,support,arm)
        def checkpoint(step,current):
            result=outcomes(current,valid);loss,reward=objective(current,inner)
            curve.append(dict(step=step,validation_wins=result['wins'],validation_changes=result['changed'],
                              fit_expected_return=float(reward.detach()),fit_loss=float(loss.detach())))
            torch.save(current.learned_state(),directory/f'inner-{step}.pt')
            print(dict(arm=arm,**curve[-1]),flush=True)
        fit(policy,inner,RECIPE['steps'],checkpoint)
        step=select_steps(curve,baseline_valid)
        final=JointEncoderPolicy(x,full_support,arm);fit(final,full,step)
        payload=dict(model_type=JointEncoderPolicy.model_type,support=full_support,arm=arm,learned=final.learned_state(),
                     selected_steps=step,base_model_sha256=x.identity['model_sha256'],recipe=RECIPE)
        torch.save(payload,directory/'candidate.pt');E.write(directory/'curve.json',curve)
        original=E.parent_model(x).state_dict()
        E.require(all(torch.equal(original[k],final.base.state_dict()[k]) for k in original),'continuation policy changed')
        if arm=='frozen':E.require(torch.equal(final.encoder_weight,final.initial_weight) and torch.equal(final.encoder_bias,final.initial_bias),'frozen encoder changed')
        report=dict(arm=arm,selected_steps=step,inner_updates=RECIPE['steps'],final_updates=step,
                    inner_validation_families=len(validation),baseline_validation_wins=baseline_valid,
                    fit_outcomes=outcomes(final,full),trainable_parameters=sum(p.numel() for p in final.parameters() if p.requires_grad),
                    continuation_unchanged=True)
        E.write(directory/'report-private.json',report);reports.append({k:v for k,v in report.items() if k!='fit_outcomes'})
    # No held labels enter fitting or stopping. Both final artifacts exist
    # before this common historical holdout is packed or scored.
    held_refs=[r for r in bundle['references'] if r['split']=='label_holdout'];E.require(len(held_refs)==1024,'held denominator changed')
    held,_=pack(helper,bundle,held_refs,full_support);add_features(JointEncoderPolicy(x,full_support,'frozen'),held)
    evaluations={}
    for arm in ARMS:
        cp=torch.load(out/arm/'candidate.pt',map_location='cpu',weights_only=True)
        evaluations[arm]=outcomes(JointEncoderPolicy(x,full_support,arm,cp['learned']),held)
        E.write(out/arm/'held-choices-private.json',evaluations[arm])
    parent=[int(r['status']=='heart_win') for r in held_refs]
    frozen=[evaluations['frozen']['targets'][r['seed']] for r in held_refs]
    candidate=[evaluations['trainable']['targets'][r['seed']] for r in held_refs]
    against_parent=x.B.paired_counts(parent,candidate);against_frozen=x.B.paired_counts(frozen,candidate)
    gate=all(r['net_gain']>=20 and r['exact_p']<.05 for r in (against_parent,against_frozen))
    result=dict(status='complete',experiment='E182',fit_families=4608,held_families=1024,arms=reports,
        frozen_vs_parent=x.B.paired_counts(parent,frozen),trainable_vs_parent=against_parent,
        trainable_vs_frozen=against_frozen,learning_gate_passed=gate,
        optimizer_updates=sum(r['inner_updates']+r['final_updates'] for r in reports),new_games=0,
        policy_adoption=False,unseen_acceptance_games=0,limits=plan['limits'])
    E.write(out/'report.json',result)
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    train(parser.parse_args().study.resolve())
