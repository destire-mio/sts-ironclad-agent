import sys
from pathlib import Path

import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_map_ablation as M


def test_removed_inputs_do_not_affect_scores_or_retained_gradients():
    torch.manual_seed(4);model=M.masked_model(dict(width=6),[1,4])
    with torch.no_grad():model.tail[-1].weight.fill_(.1)
    a=torch.randn(4,6);b=a.clone();b[:,[1,4]]+=300
    pa=model(a);pb=model(b);torch.testing.assert_close(pa,pb,rtol=0,atol=0)
    ga=torch.autograd.grad(pa.sum(),tuple(model.parameters()),retain_graph=True)
    gb=torch.autograd.grad(pb.sum(),tuple(model.parameters()))
    for x,y in zip(ga,gb):torch.testing.assert_close(x,y,rtol=0,atol=0)
    assert not ga[0][:,[1,4]].count_nonzero()


def test_mask_survives_adamw_and_unrelated_features_can_change_choice():
    torch.manual_seed(5);model=M.masked_model(dict(width=6),[1,4])
    a=torch.tensor([[1.,2.,0.,0.,3.,0.],[-1.,2.,0.,0.,3.,0.]])
    y=torch.tensor([1.,0.]);owner=torch.tensor([0,0]);opt=torch.optim.AdamW(model.parameters(),lr=.01)
    for _ in range(50):
        opt.zero_grad();loss=M.R.objective(model(a),y,owner,1,'within_state');loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(),1.);opt.step()
    assert not model.input.weight[:,[1,4]].count_nonzero()
    assert model(a)[0]>model(a)[1]
