"""Synthetic counterexample: preserving ties can bias action imitation.

This uses the actual E158 target/loss, no fitting, and no simulator data. Ten
indistinguishable public menus represent different hidden future outcomes.
"""
import argparse
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import torch


def main(source,output):
    sys.path.insert(0,str(source/'program'));import heart_exact_control as F
    F.registered(source);E=F.E
    n=10;states=np.repeat(np.arange(n),2);rewards=np.zeros(2*n);rewards[[1,3]]=1
    store=SimpleNamespace(edges=2*n,edge_state=states,state_edge_ptr=np.arange(0,2*n+1,2),
        state_edge_ids=np.arange(2*n),edge_action=np.arange(2*n),menu_ptr=np.arange(0,2*n+1,2),
        parent=np.arange(0,2*n,2),done=np.ones(2*n,dtype=bool),reward=rewards,next_state=states)
    def menu(edges):
        roots=store.edge_state[edges];actions=np.concatenate([np.array([2*s,2*s+1]) for s in roots]);ptr=np.arange(0,2*len(edges)+1,2)
        features=torch.eye(2,dtype=torch.float64).repeat(len(edges),1)
        return features,ptr,ptr[:-1],ptr[:-1],actions
    store.menu=menu;target=F.ParentPreservingTargets(store,rewards.reshape(n,2).max(axis=1),[dict(edge_begin=0,edge_end=2*n)])
    actor=torch.nn.Linear(2,1,bias=False,dtype=torch.float64)
    with torch.no_grad():actor.weight.copy_(torch.tensor([[0.,math.log(.2/.8)+3]],dtype=torch.float64))
    class Scores(torch.nn.Module):
        def forward(self,features):return actor(features).squeeze(-1)
    ids=np.arange(0,2*n,2);loss=target.losses(Scores(),ids,np.ones(2*n,dtype=bool)).mean()
    gradient=torch.autograd.grad(loss,actor.weight,create_graph=True)[0]
    curvature=torch.autograd.grad(gradient[0,1],actor.weight)[0][0,1]
    assert float(gradient.detach().abs().max())<1e-12 and float(curvature)>.1
    with torch.no_grad():probabilities=torch.softmax(actor(torch.eye(2,dtype=torch.float64)).squeeze()+torch.tensor([3.,0.]),dim=0)
    assert int(probabilities.argmax())==0
    labels=[int(x[0]%2) for x in target.targets(ids)];assert labels.count(0)==8 and labels.count(1)==2
    result=dict(status='confirmed_synthetic_counterexample',actual_loss_source_sha256=E.sha(source/'program/heart_exact_control.py'),
        hypothetical_states=n,identical_public_input=True,parent_wins=0,alternative_wins=2,
        parent_teacher_labels=8,alternative_teacher_labels=2,optimal_imitation_probabilities=probabilities.tolist(),
        loss_gradient_max=float(gradient.detach().abs().max()),positive_margin_curvature=float(curvature),
        optimal_imitation_greedy_win_rate=0.,alternative_expected_win_rate=.2,
        conclusion='Expected action agreement with a parent-on-ties hindsight teacher need not maximize expected Heart wins. More identical data preserves this population-objective mismatch.',
        limits='Constructed distribution, not an empirical collision count or measured contribution to E158 failures. It establishes a possible objective bias, not that every real state follows this distribution.',
        optimizer_updates=0,new_games=0,production_adoption=False,script_sha256=E.sha(__file__))
    E.write(output,result);print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.source.resolve(),a.output.resolve())
