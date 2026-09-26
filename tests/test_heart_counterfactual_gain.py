import sys
from pathlib import Path
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from heart_counterfactual_gain import residual_gains,select


def test_initial_network_keeps_parent_and_paired_label_moves_rare_action():
    reference=torch.nn.Linear(2,1,bias=False).double()
    network=torch.nn.Linear(2,1,bias=False).double()
    with torch.no_grad():
        reference.weight[:]=torch.tensor([[20.,-20.]])
        network.weight.copy_(reference.weight)
    features=torch.eye(2,dtype=torch.float64)
    gains=residual_gains(network,reference,features,0)
    assert torch.equal(gains,torch.zeros(2,dtype=torch.float64))
    assert select(0,[0,1],gains.detach().numpy(),[1])==0
    # The alternative has essentially zero old softmax probability, but its
    # observed positive paired return gives a direct, non-vanishing gradient.
    loss=(gains[1]-1).square();loss.backward()
    with torch.no_grad():network.weight-=.1*network.weight.grad
    gains=residual_gains(network,reference,features,0)
    assert gains[0]==0 and gains[1]>.05 and select(0,[0,1],gains.detach().numpy(),[1])==1


def test_consumed_public_action_and_nonbeneficial_prediction_keep_parent():
    assert select(0,[0,1],[0.,.2],[1],blocked=[1])==0
    assert select(0,[0,1],[0.,-.5],[1])==0
    assert select(0,[0,1],[0.,.05],[1])==0
