"""Inspect equal-return imitation targets and fitted/held E156 decisions.

No optimization or game execution. Observed-graph maxima are bounded references,
not deployable win rates. Fit appearances count each family twice; held once.
"""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import sys

import numpy as np
import torch


def bucket(values,parent):
    if np.ptp(values)<1e-10:return 'all_equal'
    return 'parent_can_improve' if values[parent]<values.max()-1e-10 else 'parent_best_with_worse_alternative'


def probabilities(values):
    exps=np.exp(values-values.max());return exps/exps.sum()


def main(source,out):
    sys.path.insert(0,str(source/'program'));import heart_exact_control as F
    E=F.E;O=F.O;torch.set_num_threads(1);torch.set_num_interop_threads(1)
    assert not out.exists();plan=F.registered(source);assert E.read(source/'result-review.json')['status']=='complete_reviewed'
    E.proof(source/'learning','completion.json');E.proof(source/'evaluation','completion-verification.json')
    old=Path(plan['learning_source']);diag=Path(plan['diagnosis']);store=O.Store(old/'store')
    values=np.load(diag/'exact-observed-values.npz',allow_pickle=False)
    q=values['q'];v=values['value'];parent_value=values['parent_value'];best=values['observed_best']
    best_q=np.where(store.done,store.reward,best[store.next_state])
    out.mkdir();E.write(out/'registration.json',dict(experiment='E157',at=datetime.now(timezone.utc).isoformat(),
        runner_sha256=E.sha(__file__),source=str(source),source_review_sha256=E.sha(source/'result-review.json'),
        exact_values_sha256=E.sha(diag/'exact-observed-values.npz'),scope='All7448 multiple-recorded-action states, all three frozen E156 actors and all128 assigned natural traces. No fitting or MCTS. Distinguish tau targets from observed maxima and deterministic parent returns.'))
    states=np.flatnonzero(np.diff(store.state_edge_ptr)>1);assert len(states)==7448
    owners=np.zeros(store.states,dtype=np.int64)
    for i,f in enumerate(store.families):owners[f['begin']:f['end']]=i
    dataset=defaultdict(Counter);inputs=[]
    for state in states:
        a,b=store.state_edge_ptr[state:state+2];edges=store.state_edge_ids[a:b]
        actions=store.edge_action[edges];parent=int(np.flatnonzero(actions==store.parent[state])[0])
        tau_q=q[edges];max_q=best_q[edges];tag=bucket(tau_q,parent);best_tag=bucket(max_q,parent)
        weights=np.minimum(100.,np.exp(10*(tau_q-v[state])));target=weights/weights.sum()
        row=dataset[tag];row['states']+=1;row['parent_target_probability_sum']+=float(target[parent])
        row['observed_max_'+best_tag]+=1
        row['expectile_below_deterministic_parent']+=int(v[state]<parent_value[state]-1e-10)
        row['all_observed_actions_fail']+=int(max_q.max()==0)
        inputs.append((int(state),edges,parent,tag,best_tag,target,weights))
    E.write(out/'target-composition.json',{k:dict(v) for k,v in dataset.items()})
    policies={};checkpoints={};choice_records=[];stats=defaultdict(Counter)
    for fold in range(3):
        cp=torch.load(source/'learning'/f'fold-{fold}'/'candidate.pt',map_location='cpu',weights_only=True);checkpoints[fold]=cp
        actor=O.Actor(store.spec['width']);actor.load_state_dict(cp['actor_state']);actor.eval();policies[fold]=actor
        supported=O.supported_candidates(store,set(cp['support']))
        for at in range(0,len(inputs),64):
            batch=inputs[at:at+64];representative=np.array([edges[0] for _,edges,*_ in batch])
            features,ptr,_,parents,actions=store.menu(representative)
            with torch.inference_mode():logits=actor(features).numpy();logits[parents]+=3.
            allowed=supported[actions].copy();allowed[parents]=True
            for i,(state,edges,parent,tag,best_tag,target,weights) in enumerate(batch):
                a,b=ptr[i:i+2];scores=logits[a:b].copy();mask=allowed[a:b];scores[~mask]=-np.inf
                parent_local=int(store.parent[state]-store.menu_ptr[state])
                choice=max(np.flatnonzero(mask),key=lambda j:(scores[j],j==parent_local,-j))
                recorded_actions=store.edge_action[edges]-store.menu_ptr[state]
                matches=np.flatnonzero(recorded_actions==choice);position=int(matches[0]) if len(matches) else None
                family=store.families[int(owners[state])];role='held' if O.T.fold(family['seed'])==fold else 'fit'
                row=stats[(role,tag)];row['appearances']+=1;row['parent_choices']+=int(choice==parent_local)
                row['unsupported_state_action']+=int(position is None)
                row['parent_probability_sum']+=float(probabilities(scores)[parent_local])
                initial_parent_probability=np.exp(3.)/(np.exp(3.)+mask.sum()-1)
                row['initial_gradient_reduces_parent_logit']+=int(initial_parent_probability>target[parent]+1e-10)
                if position is not None:
                    selected_edge=int(edges[position]);old_edge=int(edges[parent])
                    row['lower_tau_value_than_parent']+=int(q[selected_edge]<q[old_edge]-1e-10)
                    row['higher_tau_value_than_parent']+=int(q[selected_edge]>q[old_edge]+1e-10)
                    row['missed_observed_maximum']+=int(best_q[selected_edge]<best_q[edges].max()-1e-10)
                    row['observed_max_improvement_over_parent']+=int(best_q[selected_edge]>best_q[old_edge]+1e-10)
                choice_records.append([fold,state,int(choice),role])
        print(dict(stage='actors',fold=fold),flush=True)
    E.write(out/'actor-choices-private.json',choice_records)
    E.write(out/'actor-groups.json',{role:{tag:dict(values) for (r,tag),values in stats.items() if r==role} for role in ('fit','held')})
    # All first changes are at an unchanged parent state, allowing exact source
    # matching without replay or inference on a made-up counterfactual state.
    graph_source=Path(E.read(old/'protocol.json')['source'])
    continuous=Path(E.read(graph_source/'protocol.json')['continuous_source'])
    refs=E.indexed(E.read(continuous/'fit-references.json'),'seed','reference');families={f['seed']:f for f in store.families}
    x=O.C.D.runtime(plan['runtime']);kinds={getattr(x.A,k):k for k in dir(x.A) if k.startswith('AK_')}
    counts=Counter();changes=Counter();losses=Counter();records=[]
    for seed in O.T.pilot_seeds(E.read(continuous/'fit-roles.json')):
        raw=E.read(source/'evaluation/exact_graph'/f'{seed}.json.gz');old_raw=E.read(refs[seed]['path']);counts['assigned']+=1
        assert E.sha(refs[seed]['path'])==refs[seed]['sha256']
        if raw['first_change']['kind']=='unchanged':counts['unchanged']+=1;continue
        at=raw['first_change']['prefix_index'];before=raw['prefix'][at];parent_step=old_raw['prefix'][at]
        assert raw['prefix'][:at]==old_raw['prefix'][:at] and before['before']==parent_step['before']
        graph=E.read(graph_source/'families'/f'{seed}.json.gz')
        found=[i for i,r in enumerate(graph['states']) if r['fingerprint']==before['before']];assert len(found)==1
        local=found[0];row=graph['states'][local];state=families[seed]['begin']+local
        selected=row['actions'].index(before['action']);parent=row['parent'];assert row['actions'][parent]==parent_step['action']
        a,b=store.state_edge_ptr[state:state+2];edges=store.state_edge_ids[a:b]
        local_actions=(store.edge_action[edges]-store.menu_ptr[state]).tolist()
        counts['changed']+=1;kind=kinds[x.R.kind(x.R.dense(row['descriptors'][selected],store.spec['descriptor_dim']))];changes[kind]+=1
        lost=old_raw['status']=='heart_win' and raw['status']!='heart_win'
        if lost:losses[kind]+=1
        item=dict(seed=seed,lost_parent_win=lost,kind=kind,act=row['act'],floor=row['floor'],
                  chosen_recorded=selected in local_actions,recorded_actions=len(edges))
        if selected in local_actions:
            chosen_edge=int(edges[local_actions.index(selected)]);parent_edge=int(edges[local_actions.index(parent)])
            def return_parent(e):return float(store.reward[e] if store.done[e] else parent_value[store.next_state[e]])
            item.update(parent_tau_q=float(q[parent_edge]),chosen_tau_q=float(q[chosen_edge]),
                parent_observed_max=float(best_q[parent_edge]),chosen_observed_max=float(best_q[chosen_edge]),
                parent_continuation=return_parent(parent_edge),chosen_parent_continuation=return_parent(chosen_edge))
            if lost:
                counts['lost_with_recorded_worse_parent_continuation']+=int(return_parent(chosen_edge)<return_parent(parent_edge))
                counts['lost_with_lower_observed_max']+=int(best_q[chosen_edge]<best_q[parent_edge])
        else:counts['unrecorded_first_change']+=1
        records.append(item)
    E.write(out/'first-divergence-private.json',records)
    E.write(out/'first-divergence.json',dict(counts=dict(counts),kinds=dict(changes),lost_parent_wins_by_kind=dict(losses)))
    E.write(out/'completion.json',dict(status='complete',experiment='E157',optimizer_updates=0,new_games=0,
        new_training_rollouts=0,production_adoption=False,hashes={p.name:E.sha(p) for p in out.iterdir() if p.is_file()}))
    print(dict(status='complete',natural_first_changes=dict(counts)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.source.resolve(),a.output.resolve())
