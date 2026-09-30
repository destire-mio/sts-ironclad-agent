"""Checks for action exposure, return boundaries and cross-family critics."""
import copy
import math
from pathlib import Path
import sys

import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_online_actor_critic as P


def test_every_alternative_has_learnable_probability():
    p=P.prior(7,3)
    assert p[3]==.98 and np.all(p[np.arange(7)!=3]>0)
    np.testing.assert_allclose(p.sum(),1,atol=1e-15)
    residual=torch.zeros(7,dtype=torch.float64,requires_grad=True)
    log=(torch.from_numpy(np.log(p))+residual).log_softmax(0)
    log[0].backward()
    assert residual.grad[0]>.99
    assert residual.grad[3]<-.97
    assert P.prior(1,0).tolist()==[1.]


def test_terminal_value_is_zero_and_return_does_not_cross_episode():
    np.testing.assert_allclose(P.temporal([.2,.4],1),[.77,.6],atol=1e-15)
    np.testing.assert_allclose(P.temporal([.2,.4],0),[-.18,-.4],atol=1e-15)
    np.testing.assert_allclose(P.temporal([.2,.4],1,1),[.8,.6],atol=1e-15)
    np.testing.assert_allclose(P.temporal([.2],0),[-.2],atol=1e-15)


def test_critic_excludes_own_family_outcomes_and_observations():
    torch.set_num_threads(1)
    states=[[(0,float(i+1)),(1,1.)] for i in range(6)]
    targets=np.asarray([1.,1.,0.,0.,1.,1.])
    episodes=[dict(begin=i,end=i+1,family=i//2,reward=int(targets[i])) for i in range(6)]
    a,report=P.fit_critic(states,targets,episodes,0,2,0,updates=3)
    changed=copy.deepcopy(episodes);changed_states=copy.deepcopy(states);changed_targets=targets.copy()
    for i in (0,1):
        changed[i]['reward']=0;changed_targets[i]=0;changed_states[i]=[(0,-999.)]
    b,other=P.fit_critic(changed_states,changed_targets,changed,0,2,0,updates=3)
    assert report==other and report['training_families']==[1,2]
    assert all(torch.equal(v,b.state_dict()[k]) for k,v in a.state_dict().items())


def test_critic_inputs_ignore_sampled_action_and_return():
    spec=dict(state_width=2,descriptor_dim=2,width=7)
    row=dict(observation=[(0,.25)],descriptors=[[(0,1.)],[(1,1.)]],chosen=0,reward=1,seed=12)
    other=dict(row,chosen=1,reward=0,seed=999)
    assert P.state_features(row,spec)==P.state_features(other,spec)
    assert P.C.sparse_features(row,0,spec)==P.C.sparse_features(other,0,spec)


def test_numpy_matches_nonzero_policy_network():
    torch.manual_seed(47);net=P.network(6)
    torch.nn.init.normal_(net[-1].weight,std=.2)
    values=np.random.default_rng(71).normal(size=(12,6))
    with torch.no_grad():expected=net(torch.from_numpy(values))[:,0].numpy()
    np.testing.assert_allclose(P.numpy_forward(net,values),expected,atol=1e-12,rtol=0)


def test_actual_actor_update_raises_and_lowers_observed_alternative():
    torch.manual_seed(98);initial=P.network(6).state_dict()
    spec=dict(state_width=1,descriptor_dim=2,width=6)
    row=dict(observation=[(0,.5)],descriptors=[[(0,1.)],[(1,1.)]],parent=0,chosen=1,
             probabilities=[.98,.02],log_probability=math.log(.02))
    values=P.dense([P.C.sparse_features(row,j,spec) for j in (0,1)],6)
    resulting=[]
    for sign in (1.,-1.):
        net=P.network(6);net.load_state_dict(initial)
        optimizer=torch.optim.AdamW(net.parameters(),lr=.0003,weight_decay=1e-5)
        P.actor_update(net,optimizer,[row],np.asarray([sign]),spec,0)
        with torch.no_grad():scores=net(torch.from_numpy(values))[:,0].numpy()
        resulting.append(P.probabilities(np.log([.98,.02])+scores)[1])
    assert resulting[0]>.02>resulting[1]


def test_paired_result_preserves_losses_and_denominator():
    result=P.paired([True,False,False,True],[False,True,True,True])
    assert result==dict(families=4,wins=2,reference_wins=3,positive=1,negative=2,net=-1,p=1.)
