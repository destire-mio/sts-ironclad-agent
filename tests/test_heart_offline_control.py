from pathlib import Path
import sys
import copy

import numpy as np
import pytest
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_offline_control as O


def test_expectile_and_terminal_backup_have_independent_analytic_solutions():
    values=torch.tensor([0.,0.,0.,1.])
    estimate=torch.tensor(.7/(.7+3*.3),requires_grad=True)
    O.expectile_loss(values-estimate,.7).mean().backward()
    assert abs(estimate.grad)<1e-7
    reward=torch.tensor([0.,0.,1.]);done=torch.tensor([False,True,True])
    assert torch.equal(O.bellman_target(reward,done,torch.tensor([.8,.9,.4])),torch.tensor([.8,0.,1.]))
    assert torch.allclose(O.advantage_weights(torch.tensor([1.,.2]),torch.tensor([0.,.2])),torch.tensor([100.,1.]))


def test_parent_initial_actor_and_sparse_dense_serialization_agree(tmp_path):
    torch.manual_seed(4);actor=O.Actor(8);x=torch.randn(3,8)
    for features in (x,x.to_sparse()):
        scores=O.masked_actor_scores(actor(features),torch.tensor([1]),torch.tensor([True,True,True]))
        assert int(scores.argmax())==1 and scores[1]==3
    with torch.no_grad():actor.tail[-1].weight.fill_(.5)
    torch.save(actor.state_dict(),tmp_path/'actor.pt')
    restored=O.Actor(8);restored.load_state_dict(torch.load(tmp_path/'actor.pt',weights_only=True))
    assert torch.allclose(actor(x),restored(x.to_sparse()),atol=1e-6)
    values=O.masked_actor_scores(torch.tensor([100.,0.,4.]),torch.tensor([1]),torch.tensor([False,True,True]))
    assert int(values.argmax())==2  # learned advantage can override the parent; unsupported cannot


def test_sampling_balances_families_then_available_strata_and_preserves_roles():
    class Store:pass
    store=Store();store.state_edge_ptr=np.arange(11);store.state_edge_ids=np.arange(10)
    fit=[dict(seed=1,strata=[[0],[1,2,3]]),dict(seed=2,strata=[[4,5]])]
    draws=O.sample_edges(store,fit,np.random.default_rng(5).random((40000,4)))
    assert set(draws)==set(range(6)) and .48<(draws<4).mean()<.52
    assert .24<(draws==0).mean()<.26
    families=[dict(seed=i) for i in range(90) if O.T.fold(i)!=1]
    a,b=O.inner_partition(families)
    assert {f['seed'] for f in a}.isdisjoint({f['seed'] for f in b})
    assert {f['seed'] for f in a+b}=={f['seed'] for f in families}


def test_complete_observed_graph_learns_two_later_changes_beyond_parent_return():
    # At s0 the parent dies. Alternative goes to s1, where the parent also dies.
    # A second alternative reaches s2 and wins. All five transitions are observed.
    # IQL must propagate the later alternative through s1 to the earlier s0 move.
    torch.set_num_threads(1)
    class Q(torch.nn.Module):
        def __init__(self):
            super().__init__();self.a=torch.nn.Parameter(torch.full((5,),-2.1972246));self.b=torch.nn.Parameter(self.a.detach().clone())
        def forward(self,indices):return self.a[indices].sigmoid(),self.b[indices].sigmoid()
    class V(torch.nn.Module):
        def __init__(self):super().__init__();self.p=torch.nn.Parameter(torch.full((3,),-2.1972246))
        def forward(self,indices):return self.p[indices].sigmoid()
    q=Q();target=copy.deepcopy(q).requires_grad_(False);value=V()
    qo=torch.optim.Adam(q.parameters(),lr=.06);vo=torch.optim.Adam(value.parameters(),lr=.06)
    batch=dict(state_features=torch.tensor([0,0,1,1,2]),action_features=torch.arange(5),
        next_features=torch.tensor([0,1,1,2,2]),reward=torch.tensor([0.,0.,0.,0.,1.]),
        done=torch.tensor([True,False,True,False,True]))
    # Behavior favors the losing parent 2:1. A uniform fixture would leave BC
    # with an arbitrary floating-point tie, so it is not a valid losing control.
    frequencies=torch.tensor([0,0,1,2,2,3,4])
    batch={k:v[frequencies] for k,v in batch.items()}
    for _ in range(1200):O.critic_update(q,target,value,qo,vo,batch,dict(O.RECIPE,target_rate=.05))
    with torch.no_grad():
        a,b=target(torch.arange(5));weights=O.advantage_weights(torch.minimum(a,b),value(torch.tensor([0,0,1,1,2])))
    assert a[1]>.45 and a[3]>.65 and a[0]<.02 and a[2]<.02
    # Fit the same tabular categorical actor with weighted and unweighted data.
    state=torch.tensor([0,0,0,1,1,1]);chosen=torch.tensor([0,0,1,0,0,1]);results=[]
    for w in (torch.ones(6),weights[frequencies[:6]]):
        residual=torch.nn.Parameter(torch.zeros(2,2));optimizer=torch.optim.Adam([residual],lr=.04)
        for _ in range(500):
            logits=residual[state]+torch.tensor([3.,0.]);loss=(torch.nn.functional.cross_entropy(logits,chosen,reduction='none')*w).mean()
            optimizer.zero_grad();loss.backward();optimizer.step()
        policy=(residual.detach()+torch.tensor([3.,0.])).argmax(1).tolist()
        # Execute both choices in the fixture rather than checking loss alone.
        results.append(int(policy[0]==1 and policy[1]==1))
    assert results==[0,1]


def test_sparse_store_keeps_chosen_next_state_rewards_and_fit_support(tmp_path):
    E=O.E;source=tmp_path/'source';source.mkdir();continuous=tmp_path/'continuous';continuous.mkdir()
    spec=dict(state_width=2,descriptor_dim=3,width=9,support_columns=[0,1,2])
    E.write(source/'feature-spec.json',spec);E.write(source/'protocol.json',dict(continuous_source=str(continuous)))
    E.write(continuous/'fit-roles.json',[7,8])
    def row(k,parent=0):return dict(observation=[[0,k]],descriptors=[[[0,1.]],[[1,1.]]],actions=[10,20],parent=parent,act=1,floor=1,fingerprint='a'*64)
    graphs=[dict(status='complete',split='fit',seed=7,multiple_successor_state_actions=0,states=[row(.2),row(.3,1)],
        edges=[dict(state=0,action=0,next_state=1,reward=0,done=False),dict(state=0,action=1,next_state=None,reward=0,done=True),dict(state=1,action=1,next_state=None,reward=1,done=True)]),
        dict(status='complete',split='fit',seed=8,multiple_successor_state_actions=0,states=[row(.8)],edges=[dict(state=0,action=0,next_state=None,reward=0,done=True)])]
    (source/'families').mkdir();hashes={}
    import gzip,json
    for graph in graphs:
        path=source/'families'/f'{graph["seed"]}.json.gz'
        with gzip.open(path,'wt') as f:json.dump(graph,f)
        hashes[str(path)]=E.sha(path)
    E.write(source/'completion-verification.json',dict(hashes=hashes))
    O.build_store(source,tmp_path/'store');s=O.Store(tmp_path/'store')
    batch=s.batch(np.array([0,1,2,3]));assert batch['done'].tolist()==[False,True,True,True]
    assert batch['reward'].tolist()==[0.,0.,1.,0.] and s.next_state.tolist()==[1,0,1,2]
    features=batch['action_features'].to_dense()
    assert torch.allclose(features[:,0],torch.tensor([.2,.2,.3,.8]))
    assert features[:,5:8].tolist()==[[1.,0.,0.],[0.,1.,0.],[0.,1.,0.],[1.,0.,0.]]
    menu,ptr,chosen,parent,actions=s.menu(np.array([0,2]))
    assert ptr.tolist()==[0,2,4] and chosen.tolist()==[0,3] and parent.tolist()==[0,3]
    support=set(s.families[1]['support']);valid=O.supported_candidates(s,support)
    assert valid.tolist()==[True,False,True,False,True,False]


def test_unreviewed_control_source_cannot_start_learning(tmp_path):
    O.E.write(tmp_path/'registration.json',dict(runner_sha256=O.E.sha(O.__file__),hashes={}))
    O.E.write(tmp_path/'protocol.json',dict(recipe=O.RECIPE,actor_checkpoints=list(O.CHECKPOINTS),
        arms=list(O.ARMS),new_training_rollouts=0,source=str(tmp_path/'missing-source')))
    with pytest.raises(FileNotFoundError):O.train(tmp_path)
    assert not (tmp_path/'store').exists() and not (tmp_path/'learning').exists()
