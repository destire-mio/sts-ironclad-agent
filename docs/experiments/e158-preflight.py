"""Verify parent-preserving teacher labels against the entire accepted graph."""
import argparse
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0,str(root/'program'));import heart_exact_control as F
    E=F.E;O=F.O;plan=E.read(root/'protocol.json');source=Path(plan['learning_source'])
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    store=O.Store(source/'store');exact=np.load(Path(plan['diagnosis'])/'exact-observed-values.npz',allow_pickle=False)
    target=F.ParentPreservingTargets(store,exact['observed_best'],store.families)
    q=np.where(store.done,store.reward,exact['observed_best'][store.next_state])
    parental=np.flatnonzero(store.edge_action==store.parent[store.edge_state]);assert len(parental)==store.states
    teacher_edges=np.empty(store.states,dtype=np.int64);teacher_edges[store.edge_state[parental]]=parental
    changed=0
    for state in np.flatnonzero(np.diff(store.state_edge_ptr)>1):
        a,b=store.state_edge_ptr[state:state+2];edges=store.state_edge_ids[a:b]
        parent=teacher_edges[state];maximum=q[edges].max()
        expected=(np.array([store.parent[state]]) if q[parent]==maximum else store.edge_action[edges[q[edges]==maximum]])
        actual=target.targets([edges[0]])[0];np.testing.assert_array_equal(actual,expected)
        changed+=int(q[parent]<maximum)
        teacher_edges[state]=edges[np.flatnonzero(store.edge_action[edges]==actual[0])[0]]
    np.testing.assert_array_equal(q[teacher_edges],exact['observed_best'])
    assert changed==E.read(Path(plan['target_diagnosis'])/'result-review.json')['strict_observed_max_improvement_states']
    fit=[f for f in store.families if O.T.fold(f['seed'])!=0]
    target=F.ParentPreservingTargets(store,exact['observed_best'],fit)
    held=next(f for f in store.families if O.T.fold(f['seed'])==0)
    try:target.targets([held['edge_begin']])
    except ValueError as error:assert 'held family' in str(error)
    else:raise AssertionError('held labels admitted')
    supported=O.supported_candidates(store,{s for f in fit for s in f['support']})
    actor=O.new_actor(store.spec['width'],0);initial={k:v.clone() for k,v in actor.state_dict().items()}
    F.fit_actor(actor,store,fit,8,0,target,supported)
    assert any(not torch.equal(initial[k],v) for k,v in actor.state_dict().items())
    edges=np.array(E.read(source/'learning/fold-0/actor-validation.json')['edges'][:128])
    loss=F.validation_loss(actor,target,edges,supported);assert np.isfinite(loss)
    result=dict(status='passed',all_states_teacher_bellman_checked=store.states,branch_labels_checked=7448,
        strict_parent_improvement_states=changed,held_family_rejected=True,fixture_optimizer_steps=8,
        fixture_checkpoint_saved=False,formal_optimizer_steps=0,new_games=0,new_training_rollouts=0,
        loss=float(loss),script_sha256=E.sha(__file__))
    E.write(root/'preflight.json',result);print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True);main(p.parse_args().study.resolve())
