import sys
from pathlib import Path

import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_parent_prior as P


def test_zero_prior_preserves_original_initialization_and_choices():
    torch.manual_seed(48);old=P.R.V.ContinuousValue(6)
    torch.manual_seed(48);new=P.ParentPriorValue(6)
    for k,v in old.state_dict().items():torch.testing.assert_close(v,new.state_dict()[k],rtol=0,atol=0)
    a=torch.randn(5,6);v=old(a)
    torch.testing.assert_close(v,P.with_parent_prior(new(a),torch.tensor([1,4]),new.parent_bias),rtol=0,atol=0)


def test_prior_marks_the_parent_of_each_menu_and_can_be_overruled():
    q=torch.tensor([.2,.2,.9,.2,.1]);parents=torch.tensor([1,3])
    v=P.with_parent_prior(q,parents,torch.tensor(.4))
    torch.testing.assert_close(v,torch.tensor([.2,.6,.9,.6,.1]))
    assert v[:3].argmax()==2 and v[3:].argmax()==0


def test_parent_preference_is_learned_from_fit_labels_in_both_directions():
    for target,sign in [([0.,1.,0.,1.],1),([1.,0.,1.,0.],-1)]:
        bias=torch.nn.Parameter(torch.zeros(()));opt=torch.optim.AdamW([bias],lr=.03)
        for _ in range(70):
            opt.zero_grad();q=P.with_parent_prior(torch.zeros(4),torch.tensor([1,3]),bias)
            loss=P.R.objective(q,torch.tensor(target),torch.tensor([0,0,1,1]),2,'within_state')
            loss.backward();opt.step()
        assert bias.item()*sign>.9
