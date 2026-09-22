from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_exact_control as F


def fixture():
    store=SimpleNamespace(edges=11,edge_state=np.array([0]*4+[1]*4+[2]*3),
        state_edge_ptr=np.array([0,4,8,11]),state_edge_ids=np.arange(11),edge_action=np.arange(11),
        menu_ptr=np.array([0,4,8,11]),parent=np.array([3,4,9]),done=np.ones(11,dtype=bool),
        reward=np.array([0,0,0,0,0,1,1,0,1,1,1]),next_state=np.zeros(11,dtype=np.int64))
    def menu(edges):
        states=store.edge_state[edges];actions=np.concatenate([np.arange(store.menu_ptr[s],store.menu_ptr[s+1]) for s in states])
        ptr=np.r_[0,np.cumsum([store.menu_ptr[s+1]-store.menu_ptr[s] for s in states])]
        parent=ptr[:-1]+store.parent[states]-store.menu_ptr[states]
        chosen=ptr[:-1]+store.edge_action[edges]-store.menu_ptr[states]
        return torch.eye(11)[actions],ptr,chosen,parent,actions
    store.menu=menu
    return store


def test_equal_failures_and_equal_wins_keep_parent_strict_improvement_uses_winners():
    store=fixture();target=F.ParentPreservingTargets(store,np.zeros(3),[dict(edge_begin=0,edge_end=11)])
    assert [r.tolist() for r in target.targets([0,4,8])]==[[3],[5,6],[9]]
    model=torch.nn.Linear(11,1,bias=False);torch.nn.init.zeros_(model.weight)
    class Actor(torch.nn.Module):
        def forward(self,x):return model(x).squeeze(-1)
    target.losses(Actor(),np.array([0,4,8]),np.ones(11,dtype=bool)).sum().backward()
    gradient=model.weight.grad[0]
    assert gradient[3]<0 and (gradient[:3]>0).all()
    assert gradient[5]<0 and gradient[6]<0 and gradient[4]>0 and gradient[7]>0
    assert gradient[9]<0 and gradient[8]>0 and gradient[10]>0


def test_targets_do_not_read_excluded_family_or_change_with_sampled_edge():
    store=fixture();target=F.ParentPreservingTargets(store,np.zeros(3),[dict(edge_begin=0,edge_end=8)])
    assert [r.tolist() for r in target.targets([4,5,6,7])]==[[5,6]]*4
    with pytest.raises(ValueError,match='held family'):target.targets([8])
    with pytest.raises(ValueError,match='invalid edge'):target.targets([-1])
