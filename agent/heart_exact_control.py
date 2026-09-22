"""E156: replace failed neural credit propagation with exact observed-graph weights.

The E154 actor, sampler, masks, initialization, stopping and runtime are reused.
Graph state identities and returns serve only as fitting labels, never inputs.
"""
import argparse
from pathlib import Path
import time

import numpy as np
import torch

import heart_offline_control as O
import heart_offline_control_evaluation as N

E=O.E


class GraphWeights:
    def __init__(self,store,values,q,families):
        self.store=store;self.values=values;self.q=q
        self.allowed=np.zeros(store.edges,dtype=np.bool_)
        for family in families:self.allowed[family['edge_begin']:family['edge_end']]=True

    def __call__(self,edges):
        edges=np.asarray(edges,dtype=np.int64)
        E.require(bool(((edges>=0)&(edges<self.store.edges)).all()),'invalid edge index')
        E.require(bool(self.allowed[edges].all()),'held family requested as fitting label')
        advantage=self.q[edges]-self.values[self.store.edge_state[edges]]
        weights=np.exp(np.minimum(O.RECIPE['advantage_scale']*advantage,np.log(O.RECIPE['maximum_weight'])))
        E.require(bool(np.isfinite(weights).all()),'nonfinite exact control weight')
        return torch.from_numpy(weights.astype(np.float32))


def registered(root):
    reg=E.read(root/'registration.json');E.require(E.sha(__file__)==reg['runner_sha256'],'E156 runner changed')
    for path,digest in reg['hashes'].items():E.require(E.sha(path)==digest,'E156 frozen input changed: '+path)
    plan=E.read(root/'protocol.json');source=Path(plan['learning_source']);diagnosis=Path(plan['diagnosis'])
    E.require(plan['recipe']==O.RECIPE and plan['actor_checkpoints']==list(O.CHECKPOINTS),'actor recipe changed')
    O.registered(source)
    accepted=E.read(diagnosis/'result-review.json')
    E.require(accepted['status']=='complete' and accepted['graph_bellman_expectile_parent_maximum_and_acyclicity_verified']
        and accepted['exact_values_sha256']==E.sha(diagnosis/'exact-observed-values.npz'),'exact graph not admitted')
    return plan


def fit_actor(actor,store,families,steps,fold,weights,supported,on_checkpoint=None):
    rng=np.random.default_rng(O.RECIPE['seed']+1000+fold);optimizer=O.optimizer(actor)
    if on_checkpoint:on_checkpoint(0,actor)
    for step in range(1,steps+1):
        edges=O.sample_edges(store,families,rng.random((O.RECIPE['batch_size'],4)))
        loss=(O.actor_batch(actor,store,edges,supported)*weights(edges)).mean()
        O.gradient_step(loss,optimizer,actor,O.RECIPE['gradient_norm'])
        if on_checkpoint and step in O.CHECKPOINTS:on_checkpoint(step,actor)


def train(root):
    plan=registered(root);torch.set_num_threads(1);torch.set_num_interop_threads(1)
    source=Path(plan['learning_source']);store=O.Store(source/'store');diagnosis=Path(plan['diagnosis'])
    exact=np.load(diagnosis/'exact-observed-values.npz',allow_pickle=False)
    out=root/'learning';out.mkdir();models=[]
    base=torch.load(Path(plan['runtime'])/'model.pt',map_location='cpu',weights_only=True)
    for fold in range(3):
        families=[f for f in store.families if O.T.fold(f['seed'])!=fold];inner,validation=O.inner_partition(families)
        weights=GraphWeights(store,exact['value'],exact['q'],families)
        support=sorted({s for f in families for s in f['support']});supported=O.supported_candidates(store,set(support))
        rng=np.random.default_rng(O.RECIPE['seed']+2000+fold)
        edges=O.sample_edges(store,validation,rng.random((O.RECIPE['validation_draws'],4)))
        prior=E.read(source/'learning'/f'fold-{fold}'/'actor-validation.json')
        E.require(prior['edges']==edges.tolist() and prior['inner_train']==[f['seed'] for f in inner] and
                  prior['inner_validation']==[f['seed'] for f in validation],'matched actor roles/draws changed')
        directory=out/f'fold-{fold}';directory.mkdir()
        E.write(directory/'actor-validation.json',dict(prior,limits=
            'Exact graph labels stay within each family. Inner families select actor duration; the outer family is excluded from every optimization. No critic is fitted.'))
        fixed_weights=weights(edges);curve=[];started=time.monotonic()
        def checkpoint(step,actor):
            curve.append(dict(step=step,loss=O.validation_loss(actor,store,edges,fixed_weights,supported)))
            torch.save(actor.state_dict(),directory/f'inner-{step}.pt')
        actor=O.new_actor(store.spec['width'],fold)
        fit_actor(actor,store,inner,O.RECIPE['actor_steps'],fold,weights,supported,checkpoint)
        selected=min(curve,key=lambda r:(r['loss'],r['step']))['step']
        actor=O.new_actor(store.spec['width'],fold);fit_actor(actor,store,families,selected,fold,weights,supported)
        cp=dict(model_type='observed_control_actor',actor_state=actor.state_dict(),base_checkpoint=base,
            feature_spec=store.spec,support=support,parent_bonus=O.RECIPE['parent_bonus'],arm='exact_graph',
            provenance=dict(fold=fold,fit_families=[f['seed'] for f in families],selected_actor_steps=selected,
                exact_values_sha256=E.sha(diagnosis/'exact-observed-values.npz'),recipe=O.RECIPE))
        path=directory/'candidate.pt';torch.save(cp,path);E.write(directory/'stopping.json',curve)
        models.append(dict(fold=fold,path=str(path),sha256=E.sha(path),selected_actor_steps=selected,
                           seconds=time.monotonic()-started))
        print(dict(stage='actor',**models[-1]),flush=True)
    E.write(out/'report.json',dict(status='complete',models=models,critic_optimizer_steps=0,
        actor_optimizer_steps=sum(O.RECIPE['actor_steps']+r['selected_actor_steps'] for r in models),
        new_training_rollouts=0,production_adoption=False))
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in out.rglob('*') if p.is_file()}))


def evaluate(root):
    plan=registered(root);source=Path(plan['learning_source']);oldplan=E.read(source/'protocol.json')
    graph=Path(oldplan['source']);continuous=Path(E.read(graph/'protocol.json')['continuous_source'])
    out=root/'evaluation';out.mkdir();E.proof(root/'learning','completion.json')
    E.proof(source/'evaluation','completion-verification.json')
    x=O.C.D.runtime(plan['runtime']);seeds=O.T.pilot_seeds(E.read(continuous/'fit-roles.json'))
    refs=E.indexed(E.read(continuous/'fit-references.json'),'seed','reference');config=dict(x.config,workers=8)
    E.require(config['simulations']==8000 and config['boss_multiplier']==3 and config['ascension']==20,'combat budget changed')
    jobs=[]
    for seed in seeds:
        cp=root/'learning'/f'fold-{O.T.fold(seed)}'/'candidate.pt'
        jobs.append(dict(mode='prefix',arm='exact_graph',seed=seed,runtime=plan['runtime'],reference=refs[seed],
            checkpoint=str(cp),checkpoint_sha256=E.sha(cp),output=str(out/'exact_graph'/f'{seed}.json.gz')))
    deadline=time.monotonic()+plan['evaluation_timeout_seconds']
    rows=x.H.run_jobs(out,jobs,config,'E156_full_runs',deadline,worker_fn=N.evaluate_worker)
    E.require(len(rows)==len(jobs) and [r['seed'] for r in rows]==seeds,'assigned evaluation differs')
    faults=[dict(seed=r.get('seed'),status=r['status'],error=r.get('error')) for r in rows
            if r['status'] not in ('death','heart_win','act3_without_heart') or r.get('error')]
    E.write(out/'faults.json',faults);E.require(not faults,'evaluation fault; do not turn it into a loss')
    repeats=[dict(j,repeat=dict(path=j['output'],sha256=E.sha(j['output'])),
        output=str(out/'repeated'/f'{j["seed"]}.json.gz')) for j,r in zip(jobs,rows) if r['status']=='heart_win']
    repeated=x.H.run_jobs(out,repeats,config,'E156_winner_replans',deadline,worker_fn=N.evaluate_worker) if repeats else []
    E.require(len(repeated)==len(repeats) and all(r['status']=='heart_win' and r.get('fresh_replan_matched') for r in repeated),
              'fresh winning replay failed')
    chosen=[int(r['status']=='heart_win') for r in rows];comparisons={}
    comparisons['parent']=x.B.paired_counts([int(refs[s]['status']=='heart_win') for s in seeds],chosen)
    for arm in O.ARMS:
        comparisons[arm]=x.B.paired_counts([int(E.read(source/'evaluation'/arm/f'{s}.json.gz')['status']=='heart_win') for s in seeds],chosen)
    parent=comparisons['parent'];benefit=comparisons['iql']
    report=dict(status='complete',families=128,comparisons=comparisons,
        gate_passed=parent['net_gain']>=8 and parent['exact_p']<.025,
        specific_weight_repair_benefit=benefit['net_gain']>=4 and benefit['exact_p']<.05,
        natural_policy_evaluation_games=len(rows),winner_replans=len(repeats),zero_faults=True,
        new_training_rollouts=0,reserved_development_games=0,unseen_acceptance_games=0,production_adoption=False)
    E.write(out/'report.json',report)
    paths=[Path(j['output']) for j in jobs+repeats]+[out/'faults.json',out/'report.json']
    E.write(out/'completion-verification.json',dict(status='complete',zero_faults=True,
        hashes={str(p.relative_to(out)):E.sha(p) for p in paths}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('train','evaluate','check'))
    p.add_argument('--study',type=Path,required=True);a=p.parse_args();root=a.study.resolve()
    {'train':train,'evaluate':evaluate,'check':registered}[a.command](root)
