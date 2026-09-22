"""Review E158 parent-preserving targets, stopping and complete natural policy results."""
import argparse
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def training_review(root,plan,F,M):
    E=F.E;O=F.O;source=Path(plan['learning_source']);diagnosis=Path(plan['diagnosis'])
    store=O.Store(source/'store');exact=np.load(diagnosis/'exact-observed-values.npz',allow_pickle=False)
    selected=[];checkpoints=0;maximum_error=0.;candidates={}
    graph_q=np.where(store.done,store.reward,exact['observed_best'][store.next_state])
    base=torch.load(Path(plan['runtime'])/'model.pt',map_location='cpu',weights_only=True)
    for fold in range(3):
        directory=root/'learning'/f'fold-{fold}';record=E.read(directory/'actor-validation.json')
        previous=E.read(source/'learning'/f'fold-{fold}'/'actor-validation.json')
        assert all(record[k]==previous[k] for k in ('edges','inner_train','inner_validation'))
        families=[f for f in store.families if O.T.fold(f['seed'])!=fold]
        support={s for f in families for s in f['support']};allowed=O.supported_candidates(store,support)
        ids=np.array(record['edges']);state=store.edge_state[ids]
        curve=E.read(directory/'stopping.json');assert [r['step'] for r in curve]==list(O.CHECKPOINTS)
        models={r['step']:torch.load(directory/f'inner-{r["step"]}.pt',map_location='cpu',weights_only=True) for r in curve}
        initial=torch.load(source/'learning'/f'fold-{fold}'/'cloning/inner-0.pt',map_location='cpu',weights_only=True)
        assert M.same(models[0],initial)
        sums={step:0. for step in models}
        for at in range(0,len(ids),128):
            edges=ids[at:at+128];features,ptr,chosen,parent,actions=store.menu(edges);dense=features.to_dense().numpy()
            mask=allowed[actions].copy();mask[parent]=True
            for step,model in models.items():
                logits=M.forward(model,dense);logits[parent]+=3.;logits[~mask]=-np.inf
                for i,(a,b) in enumerate(zip(ptr[:-1],ptr[1:])):
                    scores=logits[a:b].astype(np.float64);high=scores.max()
                    state=int(store.edge_state[edges[i]]);u,v=store.state_edge_ptr[state:state+2]
                    recorded=store.state_edge_ids[u:v];values=graph_q[recorded]
                    original=np.flatnonzero(store.edge_action[recorded]==store.parent[state]);assert len(original)==1
                    target=(np.array([store.parent[state]]) if values[original[0]]==values.max()
                            else store.edge_action[recorded[values==values.max()]])
                    positions=target-store.menu_ptr[state]
                    assert np.isfinite(scores[positions]).all()
                    loss=high+np.log(np.exp(scores-high).sum())-scores[positions].mean()
                    sums[step]+=float(loss)
        for r in curve:
            error=abs(sums[r['step']]/len(ids)-r['loss']);maximum_error=max(maximum_error,error);assert error<1e-4
            checkpoints+=1
        step=min(curve,key=lambda r:(r['loss'],r['step']))['step'];selected.append(step)
        cp=torch.load(directory/'candidate.pt',map_location='cpu',weights_only=True);candidates[fold]=cp
        assert cp['provenance']['fold']==fold and cp['provenance']['fit_families']==[f['seed'] for f in families]
        assert cp['provenance']['selected_actor_steps']==step and cp['provenance']['recipe']==O.RECIPE
        assert cp['provenance']['actor_target']=='preserve_parent_observed_max' and cp['arm']=='parent_preserving'
        assert cp['provenance']['exact_values_sha256']==E.sha(diagnosis/'exact-observed-values.npz')
        assert cp['support']==sorted(support) and cp['feature_spec']==store.spec and cp['parent_bonus']==3
        assert M.same(cp['base_checkpoint'],base)
    learning=E.read(root/'learning/report.json');assert learning['actor_optimizer_steps']==6000+sum(selected)
    assert learning['critic_optimizer_steps']==0
    result=dict(status='training_reviewed',selected_actor_steps=selected,
        inner_checkpoints_recomputed=checkpoints,maximum_numpy_stopping_error=maximum_error,
        actor_optimizer_steps=learning['actor_optimizer_steps'],critic_optimizer_steps=0,
        registration_sha256=E.sha(root/'registration.json'),learning_completion_sha256=E.sha(root/'learning/completion.json'),
        exact_values_sha256=E.sha(diagnosis/'exact-observed-values.npz'),reviewer_sha256=E.sha(__file__),
        independent_forward_sha256=E.sha(M.__file__))
    return result,candidates


def main(root,training_only=False):
    sys.path.insert(0,str(root/'program'));import heart_exact_control as F
    E=F.E;O=F.O;torch.set_num_threads(1);torch.set_num_interop_threads(1);plan=F.registered(root)
    source=Path(plan['learning_source']);diagnosis=Path(plan['diagnosis'])
    E.proof(root/'learning','completion.json')
    train=E.read(root/'train-execution/pipeline-process-exit.json')
    assert train['exit_code']==0 and train['cleanup']['clean']
    if not training_only:
        control=root/'control';end=E.read(control/'exit.json');assert end['status']=='complete' and end['exit_code']==0
        for stage in end['stages']:
            path=root/(stage['stage']+'-execution')/'pipeline-process-exit.json'
            assert E.sha(path)==stage['proof_sha256']
            value=E.read(path);assert value['exit_code']==0 and value['cleanup']['clean']
        E.proof(root/'evaluation','completion-verification.json')
    spec=importlib.util.spec_from_file_location('independent',Path(__file__).with_name('e154-review.py'))
    M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
    cache=root/'training-review.json'
    if cache.exists():
        training=E.read(cache)
        assert training['status']=='training_reviewed' and training['reviewer_sha256']==E.sha(__file__)
        assert training['registration_sha256']==E.sha(root/'registration.json')
        assert training['learning_completion_sha256']==E.sha(root/'learning/completion.json')
        assert training['exact_values_sha256']==E.sha(diagnosis/'exact-observed-values.npz')
        assert training['independent_forward_sha256']==E.sha(M.__file__)
        candidates={fold:torch.load(root/'learning'/f'fold-{fold}'/'candidate.pt',map_location='cpu',weights_only=True) for fold in range(3)}
    else:
        training,candidates=training_review(root,plan,F,M);E.write(cache,training)
    if training_only:print(training);return
    selected=training['selected_actor_steps'];checkpoints=training['inner_checkpoints_recomputed']
    maximum_error=training['maximum_numpy_stopping_error'];learning=E.read(root/'learning/report.json')
    old=E.read(source/'protocol.json');graph=Path(old['source']);continuous=Path(E.read(graph/'protocol.json')['continuous_source'])
    seeds=O.T.pilot_seeds(E.read(continuous/'fit-roles.json'));refs=E.indexed(E.read(continuous/'fit-references.json'),'seed','reference')
    x=O.C.D.runtime(plan['runtime']);policies={fold:O.ControlPolicy(cp,x) for fold,cp in candidates.items()}
    chosen=[];win_repeats=0;outside=0
    for seed in seeds:
        fold=O.T.fold(seed);cp=candidates[fold];assert seed not in cp['provenance']['fit_families']
        raw=E.read(root/'evaluation/parent_preserving'/f'{seed}.json.gz')
        assert raw['seed']==seed and raw['checkpoint_sha256']==E.sha(root/'learning'/f'fold-{fold}'/'candidate.pt')
        assert raw['engine_sha256']==plan['identity']['engine_sha256']
        audit=F.N.audit_route(x,raw,policies[fold],cp);assert audit==raw['audit'];outside+=audit['outside_choices']
        assert E.sha(refs[seed]['path'])==refs[seed]['sha256'];parent=E.read(refs[seed]['path'])
        assert F.N.first_change(x,parent,raw)==raw['first_change'];chosen.append(int(raw['status']=='heart_win'))
        if raw['status']=='heart_win':
            repeated=E.read(root/'evaluation/repeated'/f'{seed}.json.gz')
            assert repeated['fresh_replan_matched'] and repeated['status']=='heart_win' and repeated['prefix']==raw['prefix']
            assert x.P.terminal_signature(repeated)==x.P.terminal_signature(raw)
            assert F.N.audit_route(x,repeated,policies[fold],cp)==repeated['audit'];win_repeats+=1
    comparisons={'parent':M.paired([int(refs[s]['status']=='heart_win') for s in seeds],chosen)}
    for arm in O.ARMS:
        comparisons[arm]=M.paired([int(E.read(source/'evaluation'/arm/f'{s}.json.gz')['status']=='heart_win') for s in seeds],chosen)
    preceding=Path(plan['preceding_actor_study']);E.proof(preceding/'evaluation','completion-verification.json')
    comparisons['exact_graph']=M.paired([int(E.read(preceding/'evaluation/exact_graph'/f'{s}.json.gz')['status']=='heart_win') for s in seeds],chosen)
    report=E.read(root/'evaluation/report.json');assert report['comparisons']==comparisons and report['winner_replans']==win_repeats
    assert report['gate_passed']==(comparisons['parent']['net_gain']>=8 and comparisons['parent']['exact_p']<.025)
    assert report['specific_target_repair_benefit']==(comparisons['exact_graph']['net_gain']>=4 and comparisons['exact_graph']['exact_p']<.05)
    result=dict(status='complete_reviewed',experiment='E158',**{k:v for k,v in report.items() if k!='status'},
        inner_checkpoints_recomputed=checkpoints,maximum_numpy_stopping_error=maximum_error,
        selected_actor_steps=selected,actor_optimizer_steps=learning['actor_optimizer_steps'],
        verified_outside_choices=outside,controller_exit_sha256=E.sha(control/'exit.json'),
        completion_sha256=E.sha(root/'evaluation/completion-verification.json'),reviewer_sha256=E.sha(__file__))
    E.write(root/'result-review.json',result);print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    p.add_argument('--training-only',action='store_true');a=p.parse_args();main(a.study.resolve(),a.training_only)
