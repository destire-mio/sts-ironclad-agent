"""Review E156 stopping with NumPy and verify every natural route and winning rerun."""
import argparse
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0,str(root/'program'));import heart_exact_control as F
    E=F.E;O=F.O;torch.set_num_threads(1);torch.set_num_interop_threads(1);plan=F.registered(root)
    source=Path(plan['learning_source']);diagnosis=Path(plan['diagnosis'])
    end=E.read(root/'control/exit.json');assert end['status']=='complete' and end['exit_code']==0
    for stage in end['stages']:
        path=root/(stage['stage']+'-execution')/'pipeline-process-exit.json'
        assert E.sha(path)==stage['proof_sha256']
        value=E.read(path);assert value['exit_code']==0 and value['cleanup']['clean']
    E.proof(root/'learning','completion.json');E.proof(root/'evaluation','completion-verification.json')
    spec=importlib.util.spec_from_file_location('independent',Path(__file__).with_name('e154-review.py'))
    M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
    store=O.Store(source/'store');exact=np.load(diagnosis/'exact-observed-values.npz',allow_pickle=False)
    selected=[];checkpoints=0;maximum_error=0.;candidates={}
    base=torch.load(Path(plan['runtime'])/'model.pt',map_location='cpu',weights_only=True)
    for fold in range(3):
        directory=root/'learning'/f'fold-{fold}';record=E.read(directory/'actor-validation.json')
        previous=E.read(source/'learning'/f'fold-{fold}'/'actor-validation.json')
        assert all(record[k]==previous[k] for k in ('edges','inner_train','inner_validation'))
        families=[f for f in store.families if O.T.fold(f['seed'])!=fold]
        support={s for f in families for s in f['support']};allowed=O.supported_candidates(store,support)
        ids=np.array(record['edges']);state=store.edge_state[ids]
        weights=np.minimum(100.,np.exp(10*(exact['q'][ids]-exact['value'][state])))
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
                    loss=high+np.log(np.exp(scores-high).sum())-logits[chosen[i]]
                    sums[step]+=float(loss*weights[at+i])
        for r in curve:
            error=abs(sums[r['step']]/len(ids)-r['loss']);maximum_error=max(maximum_error,error);assert error<1e-4
            checkpoints+=1
        step=min(curve,key=lambda r:(r['loss'],r['step']))['step'];selected.append(step)
        cp=torch.load(directory/'candidate.pt',map_location='cpu',weights_only=True);candidates[fold]=cp
        assert cp['provenance']['fold']==fold and cp['provenance']['fit_families']==[f['seed'] for f in families]
        assert cp['provenance']['selected_actor_steps']==step and cp['provenance']['recipe']==O.RECIPE
        assert cp['provenance']['exact_values_sha256']==E.sha(diagnosis/'exact-observed-values.npz')
        assert cp['support']==sorted(support) and cp['feature_spec']==store.spec and cp['parent_bonus']==3
        assert M.same(cp['base_checkpoint'],base)
    learning=E.read(root/'learning/report.json');assert learning['actor_optimizer_steps']==6000+sum(selected)
    assert learning['critic_optimizer_steps']==0
    old=E.read(source/'protocol.json');graph=Path(old['source']);continuous=Path(E.read(graph/'protocol.json')['continuous_source'])
    seeds=O.T.pilot_seeds(E.read(continuous/'fit-roles.json'));refs=E.indexed(E.read(continuous/'fit-references.json'),'seed','reference')
    x=O.C.D.runtime(plan['runtime']);policies={fold:O.ControlPolicy(cp,x) for fold,cp in candidates.items()}
    chosen=[];win_repeats=0;outside=0
    for seed in seeds:
        fold=O.T.fold(seed);cp=candidates[fold];assert seed not in cp['provenance']['fit_families']
        raw=E.read(root/'evaluation/exact_graph'/f'{seed}.json.gz')
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
    report=E.read(root/'evaluation/report.json');assert report['comparisons']==comparisons and report['winner_replans']==win_repeats
    assert report['gate_passed']==(comparisons['parent']['net_gain']>=8 and comparisons['parent']['exact_p']<.025)
    assert report['specific_weight_repair_benefit']==(comparisons['iql']['net_gain']>=4 and comparisons['iql']['exact_p']<.05)
    result=dict(status='complete_reviewed',experiment='E156',**{k:v for k,v in report.items() if k!='status'},
        inner_checkpoints_recomputed=checkpoints,maximum_numpy_stopping_error=maximum_error,
        selected_actor_steps=selected,actor_optimizer_steps=learning['actor_optimizer_steps'],
        verified_outside_choices=outside,controller_exit_sha256=E.sha(root/'control/exit.json'),
        completion_sha256=E.sha(root/'evaluation/completion-verification.json'),reviewer_sha256=E.sha(__file__))
    E.write(root/'result-review.json',result);print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True);main(p.parse_args().study.resolve())
