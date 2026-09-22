import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_alternative_ranking as R


def test_within_state_loss_is_invariant_to_separate_state_offsets():
    q=torch.tensor([.4,.8,.2,.1,.9],requires_grad=True)
    y=torch.tensor([0.,1.,1.,0.,0.]);owner=torch.tensor([0,0,1,1,1])
    loss=R.objective(q,y,owner,2,'within_state');g=torch.autograd.grad(loss,q)[0]
    moved=R.objective(q+torch.tensor([4.,4.,-3.,-3.,-3.]),y,owner,2,'within_state')
    torch.testing.assert_close(loss,moved);torch.testing.assert_close(g,torch.autograd.grad(moved,q)[0])
    assert not torch.isclose(R.objective(q,y,owner,2,'absolute'),R.objective(q+1,y,owner,2,'absolute'))


def test_loss_and_gradient_match_explicit_pair_comparisons():
    q=torch.tensor([.1,.8,-.7,.2,.4],dtype=torch.float64,requires_grad=True)
    y=torch.tensor([1.,0.,1.,1.,0.],dtype=torch.float64);owner=torch.tensor([0,0,1,1,1])
    groups=[]
    for ids in ([0,1],[2,3,4]):
        groups.append(sum(((q[i]-q[j])-(y[i]-y[j]))**2 for i in ids for j in ids)/(2*len(ids)**2))
    expected=sum(groups)/len(groups);actual=R.objective(q,y,owner,2,'within_state')
    torch.testing.assert_close(actual,expected)
    torch.testing.assert_close(torch.autograd.grad(actual,q,retain_graph=True)[0],torch.autograd.grad(expected,q)[0])


def test_equal_outcomes_do_not_invent_a_preference_and_swapping_reverses_it():
    owner=torch.tensor([0,0,1,1]);q=torch.tensor([.3,.3,.8,.8],requires_grad=True)
    tied=R.objective(q,torch.tensor([0.,0.,1.,1.]),owner,2,'within_state')
    assert tied.item()==0;assert torch.autograd.grad(tied,q)[0].count_nonzero()==0
    def gradient(y):return torch.autograd.grad(R.objective(q,torch.tensor(y),owner,2,'within_state'),q)[0]
    a=gradient([1.,0.,0.,1.]);b=gradient([0.,1.,1.,0.])
    torch.testing.assert_close(a,-b);assert a[0]<0 and a[1]>0


def test_family_and_stage_balanced_sampling_stays_in_fit():
    families=[dict(seed=1,stages=[[0],[1],[2,3,4,5]]),dict(seed=2,stages=[[6]])]
    u=np.random.default_rng(22).random((60000,3));rows=R.sample_rows(families,u)
    assert set(rows)==set(range(7))
    assert .49<(rows==6).mean()<.51
    assert .15<(rows==0).mean()<.18 and .15<(rows==1).mean()<.18
    assert .15<np.isin(rows,[2,3,4,5]).mean()<.18


def test_nonlinear_model_learns_opposite_actions_for_opposite_contexts():
    torch.set_num_threads(1);torch.manual_seed(48)
    model=R.V.ContinuousValue(2);torch.nn.init.zeros_(model.tail[-1].bias)
    x=torch.tensor([[-1.,-1.],[-1.,1.],[1.,-1.],[1.,1.]])
    y=torch.tensor([1.,0.,0.,1.]);owner=torch.tensor([0,0,1,1])
    opt=torch.optim.AdamW(model.parameters(),lr=.01)
    for _ in range(100):
        opt.zero_grad();loss=R.objective(model(x),y,owner,2,'within_state');loss.backward();opt.step()
    with torch.no_grad():v=model(x).reshape(2,2)
    assert v.argmax(1).tolist()==[0,1] and loss<.001


def test_tree_evaluation_never_combines_incompatible_first_card_and_boss_prefixes():
    f=dict(seed=1,parent_target=0,first_card=0,boss=1,
           branches=[dict(candidate=0,target=1,card=2),dict(candidate=1,target=0,card=3)])
    states=[{},dict(parent=0),{},{}]
    choices={0:dict(candidate=3,target=1),1:dict(candidate=1,target=0),
             2:dict(candidate=0,target=0),3:dict(candidate=2,target=1)}
    r=R.family_results([f],states,choices)[0]
    assert r['targets']==dict(first_card=1,boss_only=0,parent_boss_then_card=0,boss_then_card=1)
    assert r['choices']==dict(first_card=3,relic=1,card=2,parent_relic_card=0)
