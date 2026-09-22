"""Observed-action IQL and matched cloning on complete existing trajectories.

Discrete adaptation of Kostrikov et al., arXiv:2110.06169. Critics query only
recorded actions, V uses an upper expectile, and the deployed actor is fitted
by advantage-weighted log likelihood. It does not maximize Q over unseen moves.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

import heart_control_data as G
import heart_continuous_training as T

C,V,E = T.C,T.V,T.E
ARMS = ('cloning','iql')
CHECKPOINTS = (0,25,50,100,250,500,1000,2000)
RECIPE = dict(critic_steps=20000,batch_size=128,learning_rate=.0003,weight_decay=.0001,
              gradient_norm=1.,expectile=.7,target_rate=.005,advantage_scale=10.,
              maximum_weight=100.,discount=1.,parent_bonus=3.,validation_draws=8192,
              actor_steps=2000,seed=2026092254)


def expectile_loss(difference, expectile):
    E.require(0 < expectile < 1, 'expectile outside unit interval')
    return torch.where(difference>0,expectile,1-expectile)*difference.square()


def bellman_target(reward, done, next_value):
    return reward + (~done).to(next_value.dtype)*next_value


def advantage_weights(q, value, scale=10., maximum=100.):
    return torch.exp(torch.clamp((q-value)*scale,max=math.log(maximum))).detach()


class ProbabilityValue(V.ContinuousValue):
    def forward(self, features):
        return super().forward(features).sigmoid()


class TwinValue(torch.nn.Module):
    def __init__(self,width):
        super().__init__()
        self.q1=ProbabilityValue(width); self.q2=ProbabilityValue(width)

    def forward(self,features):
        return self.q1(features),self.q2(features)


class Actor(V.ContinuousValue):
    def __init__(self,width):
        super().__init__(width)
        torch.nn.init.zeros_(self.tail[-1].bias)


def gradient_step(loss, optimizer, model, norm):
    E.require(bool(torch.isfinite(loss)), 'nonfinite learning objective')
    optimizer.zero_grad();loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(),norm,error_if_nonfinite=True)
    optimizer.step()


def critic_update(q,target_q,value,q_optimizer,v_optimizer,batch,recipe=RECIPE):
    with torch.no_grad():
        a,b=target_q(batch['action_features']); target=torch.minimum(a,b)
    predicted=value(batch['state_features'])
    v_loss=expectile_loss(target-predicted,recipe['expectile']).mean()
    gradient_step(v_loss,v_optimizer,value,recipe['gradient_norm'])
    with torch.no_grad():
        next_value=value(batch['next_features'])
        target=bellman_target(batch['reward'],batch['done'],next_value)
    a,b=q(batch['action_features'])
    q_loss=((a-target).square()+(b-target).square()).mean()
    gradient_step(q_loss,q_optimizer,q,recipe['gradient_norm'])
    with torch.no_grad():
        for delayed,current in zip(target_q.parameters(),q.parameters()):
            delayed.lerp_(current,recipe['target_rate'])
    return dict(q_loss=float(q_loss.detach()),v_loss=float(v_loss.detach()),
                q_mean=float(a.detach().mean()),v_mean=float(predicted.detach().mean()))


def categorise(states,edges):
    outgoing=[[] for _ in states]
    for i,edge in enumerate(edges):outgoing[edge['state']].append(i)
    strata=[[],[],[]]
    for i,options in enumerate(outgoing):
        E.require(options,'state has no recorded successor')
        E.require(len({edges[j]['action'] for j in options})==len(options), 'ambiguous observed transition')
        group=0 if len(options)>1 else 1 if edges[options[0]]['done'] else 2
        strata[group].append(i)
    return outgoing,[group for group in strata if group]


def build_store(source,output):
    output.mkdir();spec=E.read(source/'feature-spec.json')
    plan=E.read(source/'protocol.json');roles=E.read(Path(plan['continuous_source'])/'fit-roles.json')
    proof=E.read(source/'completion-verification.json')
    shared,desc=T.Builder(),T.Builder()
    menu_ptr=[0];parent=[];edge_state=[];edge_action=[];next_state=[];reward=[];done=[]
    identities=[];identity_lookup={};candidate_identity=[];support_columns=set(spec['support_columns'])
    state_edge_ptr=[0];state_edge_ids=[];families=[];state_count=0
    for number,seed in enumerate(roles):
        path=source/'families'/f'{seed}.json.gz'
        E.require(E.sha(path)==proof['hashes'][str(path)], 'graph family changed')
        graph=E.read(path)
        E.require(graph['status']=='complete' and graph['split']=='fit' and graph['seed']==seed and
                  graph['multiple_successor_state_actions']==0, 'invalid admitted graph')
        states,edges=graph['states'],graph['edges'];begin=state_count;edge_begin=len(edge_state)
        outgoing,strata=categorise(states,edges);support=set()
        for i,row in enumerate(states):
            means=Counter();n=len(row['descriptors'])
            for d in row['descriptors']:
                for j,v in d:means[j]+=v/n
            shared.append([(j,v) for j,v in row['observation']]+
                [(spec['state_width']+j,v) for j,v in sorted(means.items()) if v]+
                [(spec['width']-1,n/64.)],spec['width'])
            start=menu_ptr[-1]
            for d in row['descriptors']:
                desc.append(d,spec['descriptor_dim'])
                key=tuple((int(j),float(v)) for j,v in d if j in support_columns and v!=0)
                if key not in identity_lookup:
                    identity_lookup[key]=len(identities)
                    identities.append(hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).hexdigest())
                candidate_identity.append(identity_lookup[key])
            parent.append(start+row['parent']);menu_ptr.append(start+n)
            state_edge_ids.extend(edge_begin+j for j in outgoing[i]);state_edge_ptr.append(len(state_edge_ids))
        for e in edges:
            state=e['state'];row=states[state]
            E.require(0<=e['action']<len(row['actions']) and (e['next_state'] is None)==e['done'] and
                      e['reward'] in (0,1) and (e['done'] or e['reward']==0), 'invalid transition/reward')
            edge_state.append(begin+state);edge_action.append(menu_ptr[begin+state]+e['action'])
            # Terminal rows use their own state as a harmless masked placeholder.
            next_state.append(begin+(state if e['done'] else e['next_state']))
            reward.append(e['reward']);done.append(e['done'])
            support.add(identities[candidate_identity[menu_ptr[begin+state]+e['action']]])
        state_count+=len(states)
        families.append(dict(seed=seed,begin=begin,end=state_count,edge_begin=edge_begin,edge_end=len(edge_state),
            strata=[[begin+i for i in group] for group in strata],support=sorted(support)))
        if (number+1)%128==0:print(dict(stage='store',families=number+1,states=state_count,edges=len(edge_state)),flush=True)
    shared.save(output,'shared');desc.save(output,'descriptors')
    arrays=dict(menu_ptr=menu_ptr,parent=parent,edge_state=edge_state,edge_action=edge_action,next_state=next_state,
                reward=reward,done=done,state_edge_ptr=state_edge_ptr,state_edge_ids=state_edge_ids,
                candidate_identity=candidate_identity)
    for name,values in arrays.items():
        dtype=np.bool_ if name=='done' else np.float32 if name=='reward' else np.int64
        np.save(output/(name+'.npy'),np.asarray(values,dtype=dtype),allow_pickle=False)
    E.write(output/'metadata.json',dict(spec=spec,families=families,states=state_count,edges=len(edge_state),
                                      identities=identities))
    E.write(output/'completion.json',dict(status='complete',hashes={p.name:E.sha(p) for p in output.iterdir()}))


class Store:
    def __init__(self,path,verify=True):
        if verify:E.proof(path,'completion.json')
        meta=E.read(path/'metadata.json');self.spec=meta['spec'];self.families=meta['families']
        self.states=meta['states'];self.edges=meta['edges']
        self.identities=meta['identities']
        self.shared=T.SparseTable(path,'shared',self.spec['width'])
        self.descriptors=T.SparseTable(path,'descriptors',self.spec['descriptor_dim'])
        for name in ('menu_ptr','parent','edge_state','edge_action','next_state','reward','done',
                     'state_edge_ptr','state_edge_ids','candidate_identity'):
            setattr(self,name,np.load(path/(name+'.npy'),mmap_mode='r',allow_pickle=False))

    def action_features(self,states,actions):
        base=self.shared.take(states);candidate=self.descriptors.take(actions)
        index=candidate.indices().clone();index[1]+=self.spec['state_width']+self.spec['descriptor_dim']
        return torch.sparse_coo_tensor(torch.cat([base.indices(),index],dim=1),
            torch.cat([base.values(),candidate.values()]),base.shape,check_invariants=True).coalesce()

    def batch(self,edges):
        states=self.edge_state[edges]
        return dict(state_features=self.shared.take(states),
            action_features=self.action_features(states,self.edge_action[edges]),
            next_features=self.shared.take(self.next_state[edges]),
            reward=torch.from_numpy(self.reward[edges].copy()),done=torch.from_numpy(self.done[edges].copy()))

    def menu(self,edges):
        states=self.edge_state[edges];starts,ends=self.menu_ptr[states],self.menu_ptr[states+1]
        sizes=ends-starts;owners=np.repeat(np.arange(len(states)),sizes)
        actions=np.concatenate([np.arange(a,b) for a,b in zip(starts,ends)])
        ptr=np.concatenate([[0],np.cumsum(sizes)])
        chosen=ptr[:-1]+self.edge_action[edges]-starts
        parent=ptr[:-1]+self.parent[states]-starts
        return self.action_features(states[owners],actions),ptr,chosen,parent,actions


def sample_edges(store,families,uniforms):
    edges=[]
    def pick(seq,u):return seq[min(int(u*len(seq)),len(seq)-1)]
    for u in uniforms:
        family=pick(families,u[0]);group=pick(family['strata'],u[1]);state=pick(group,u[2])
        start,end=store.state_edge_ptr[state:state+2]
        edges.append(int(store.state_edge_ids[start+min(int(u[3]*(end-start)),end-start-1)]))
    return np.asarray(edges,dtype=np.int64)


def masked_actor_scores(logits,parent,allowed,bonus=3.):
    values=logits.clone();values[parent]+=bonus
    return values.masked_fill(~allowed,-torch.inf)


def actor_losses(scores,ptr,chosen):
    return torch.stack([torch.logsumexp(scores[int(a):int(b)],0)-scores[int(c)]
                        for a,b,c in zip(ptr[:-1],ptr[1:],chosen)])


def supported_candidates(store,support):
    # Vocabulary codes store categorical descriptors, not family/state IDs.
    allowed=np.asarray([k in support for k in store.identities],dtype=np.bool_)
    return allowed[store.candidate_identity]


def actor_batch(actor,store,edges,supported):
    features,ptr,chosen,parent,actions=store.menu(edges)
    allowed=torch.from_numpy(supported[actions].copy());allowed[parent]=True
    E.require(bool(allowed[chosen].all()), 'recorded fitting action lost support')
    scores=masked_actor_scores(actor(features),parent,allowed,RECIPE['parent_bonus'])
    return actor_losses(scores,ptr,chosen)


def weights_for(store,edges,q,value,arm):
    if arm=='cloning':return torch.ones(len(edges))
    E.require(arm=='iql','unknown actor arm')
    with torch.no_grad():
        state=store.edge_state[edges]
        a,b=q(store.action_features(state,store.edge_action[edges]))
        v=value(store.shared.take(state))
        return advantage_weights(torch.minimum(a,b),v,RECIPE['advantage_scale'],RECIPE['maximum_weight'])


def inner_partition(families):
    valid=[f for f in families if int(hashlib.sha256(f'E151-inner:{f["seed"]}'.encode()).hexdigest(),16)%5==0]
    held={f['seed'] for f in valid};train=[f for f in families if f['seed'] not in held]
    E.require(train and valid,'empty actor fitting or validation partition')
    return train,valid


def validation_loss(actor,store,edges,weights,supported):
    total=0.
    with torch.no_grad():
        for at in range(0,len(edges),128):
            losses=actor_batch(actor,store,edges[at:at+128],supported)
            total+=float((losses*weights[at:at+128]).sum())
    return total/len(edges)


def optimizer(model):
    return torch.optim.AdamW(model.parameters(),lr=RECIPE['learning_rate'],weight_decay=RECIPE['weight_decay'])


def new_actor(width,fold):
    torch.manual_seed(RECIPE['seed']+100+fold)
    return Actor(width)


def train_critic(store,families,fold,output):
    torch.manual_seed(RECIPE['seed']+fold);rng=np.random.default_rng(RECIPE['seed']+fold)
    q=TwinValue(store.spec['width']);target_q=copy.deepcopy(q).requires_grad_(False)
    value=ProbabilityValue(store.spec['width']);q_opt,v_opt=optimizer(q),optimizer(value)
    curve=[];started=time.monotonic()
    for step in range(1,RECIPE['critic_steps']+1):
        edges=sample_edges(store,families,rng.random((RECIPE['batch_size'],4)))
        info=critic_update(q,target_q,value,q_opt,v_opt,store.batch(edges))
        if step%2000==0:
            curve.append(dict(step=step,**info));print(dict(stage='critic',fold=fold,**curve[-1]),flush=True)
    torch.save(dict(q=q.state_dict(),target_q=target_q.state_dict(),value=value.state_dict(),
        fit_families=[f['seed'] for f in families],fold=fold,recipe=RECIPE),output/'critic.pt')
    E.write(output/'critic-curve.json',curve)
    return target_q.eval(),value.eval(),time.monotonic()-started


def fit_actor(actor,store,families,steps,fold,arm,q,value,supported,on_checkpoint=None):
    rng=np.random.default_rng(RECIPE['seed']+1000+fold);opt=optimizer(actor)
    if on_checkpoint:on_checkpoint(0,actor)
    for step in range(1,steps+1):
        edges=sample_edges(store,families,rng.random((RECIPE['batch_size'],4)))
        weights=weights_for(store,edges,q,value,arm)
        loss=(actor_batch(actor,store,edges,supported)*weights).mean()
        gradient_step(loss,opt,actor,RECIPE['gradient_norm'])
        if on_checkpoint and step in CHECKPOINTS:on_checkpoint(step,actor)


def registered(root):
    reg=E.read(root/'registration.json')
    E.require(E.sha(__file__)==reg['runner_sha256'],'offline-control runner changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'registered input changed: '+p)
    plan=E.read(root/'protocol.json')
    E.require(plan['recipe']==RECIPE and plan['actor_checkpoints']==list(CHECKPOINTS) and
              plan['arms']==list(ARMS) and plan['new_training_rollouts']==0,'registered recipe differs')
    source=Path(plan['source']);review=E.read(source/'result-review.json')
    E.require(review['status']=='complete' and review['zero_faults'] and
              review['completion_sha256']==E.sha(source/'completion-verification.json'), 'control graph not accepted')
    return plan


def train(root):
    plan=registered(root);torch.set_num_threads(1);torch.set_num_interop_threads(1)
    source=Path(plan['source']);build_store(source,root/'store');store=Store(root/'store')
    roles=[f['seed'] for f in store.families];out=root/'learning';out.mkdir()
    x=C.D.runtime(plan['runtime']);base=torch.load(x.directory/'model.pt',weights_only=True,map_location='cpu')
    summary={};models=[]
    for fold in range(3):
        families=[f for f in store.families if T.fold(f['seed'])!=fold]
        inner,validation=inner_partition(families)
        support=sorted({s for f in families for s in f['support']})
        supported=supported_candidates(store,set(support))
        directory=out/f'fold-{fold}';directory.mkdir()
        q,value,critic_seconds=train_critic(store,families,fold,directory)
        fixed_rng=np.random.default_rng(RECIPE['seed']+2000+fold)
        validation_edges=sample_edges(store,validation,fixed_rng.random((RECIPE['validation_draws'],4)))
        E.write(directory/'actor-validation.json',dict(inner_train=[f['seed'] for f in inner],
            inner_validation=[f['seed'] for f in validation],edges=validation_edges.tolist(),
            limits='This partition controls actor stopping only. Its frozen critic uses all outer-fit families; the outer family remains excluded from both.'))
        for arm in ARMS:
            path=directory/arm;path.mkdir();started=time.monotonic();curve=[]
            weights=weights_for(store,validation_edges,q,value,arm)
            def checkpoint(step,actor):
                loss=validation_loss(actor,store,validation_edges,weights,supported)
                curve.append(dict(step=step,loss=loss));torch.save(actor.state_dict(),path/f'inner-{step}.pt')
            actor=new_actor(store.spec['width'],fold)
            fit_actor(actor,store,inner,RECIPE['actor_steps'],fold,arm,q,value,supported,checkpoint)
            selected=min(curve,key=lambda r:(r['loss'],r['step']))['step']
            actor=new_actor(store.spec['width'],fold)
            fit_actor(actor,store,families,selected,fold,arm,q,value,supported)
            cp=dict(model_type='observed_control_actor',actor_state=actor.state_dict(),base_checkpoint=base,
                feature_spec=store.spec,support=support,parent_bonus=RECIPE['parent_bonus'],arm=arm,
                provenance=dict(fold=fold,fit_families=[f['seed'] for f in families],
                    selected_actor_steps=selected,critic_sha256=E.sha(directory/'critic.pt'),
                    graph_completion_sha256=E.sha(source/'completion-verification.json'),recipe=RECIPE))
            torch.save(cp,path/'candidate.pt');E.write(path/'stopping.json',curve)
            models.append(dict(arm=arm,fold=fold,path=str(path/'candidate.pt'),sha256=E.sha(path/'candidate.pt'),
                               selected_actor_steps=selected,seconds=time.monotonic()-started))
            print(dict(stage='actor',arm=arm,fold=fold,selected_steps=selected),flush=True)
        summary[str(fold)]=dict(fit_families=len(families),critic_steps=RECIPE['critic_steps'],critic_seconds=critic_seconds)
    E.write(out/'report.json',dict(status='complete',folds=summary,models=models,
        critic_updates=3*RECIPE['critic_steps'],critic_optimizer_steps=6*RECIPE['critic_steps'],
        actor_optimizer_steps=sum(RECIPE['actor_steps']+m['selected_actor_steps'] for m in models),
        total_optimizer_steps=6*RECIPE['critic_steps']+sum(RECIPE['actor_steps']+m['selected_actor_steps'] for m in models),
        new_training_rollouts=0,production_adoption=False))
    paths=[p for p in out.rglob('*') if p.is_file()]
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in paths}))


class ControlPolicy(torch.nn.Module):
    def __init__(self,checkpoint,x):
        super().__init__();E.require(checkpoint['model_type']=='observed_control_actor','wrong model type')
        E.require(checkpoint['feature_spec']==C.spec_for(x),'changed public feature schema')
        self.x=x;self.spec=checkpoint['feature_spec'];self.support=set(checkpoint['support'])
        self.bonus=checkpoint['parent_bonus'];self.base=x.H.load_scorer(checkpoint['base_checkpoint']).eval()
        self.actor=Actor(self.spec['width']);self.actor.load_state_dict(checkpoint['actor_state'])
        self.requires_grad_(False);self.eval()

    def choose(self,gc,observation,actions,descriptors):
        parent=self.base.choose(gc,observation,actions,descriptors)
        if len(actions)==1:return parent
        row=dict(observation=self.x.R.sparse([observation[i] for i in self.spec['observations']]),
                 descriptors=[self.x.R.sparse(d) for d in descriptors])
        values=torch.zeros((len(actions),self.spec['width']))
        for i in range(len(actions)):
            pairs=C.sparse_features(row,i,self.spec)
            values[i,[j for j,_ in pairs]]=torch.tensor([v for _,v in pairs],dtype=torch.float32)
        with torch.inference_mode():
            scores=self.actor(values);scores[parent]+=self.bonus
        return V.select(row,scores.tolist(),parent,self.support,self.spec)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','train'));parser.add_argument('--study',type=Path,required=True)
    args=parser.parse_args();root=args.study.resolve()
    registered(root) if args.command=='check' else train(root)
