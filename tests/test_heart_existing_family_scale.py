import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_existing_family_scale as S


def family(seed,first=None,boss=None,cards=()):
    return dict(seed=seed,first_card=first,boss=boss,branches=[dict(card=i) for i in cards])


def test_expansion_keeps_first_card_draws_and_stage_exposure_matched():
    small=[family(1,0,1,[2,3]),family(2,4)]
    expanded=small+[family(3,boss=5,cards=[6,7,8]),family(4)]
    a=S.stage_pools(small);b=S.stage_pools(expanded)
    uniform=np.random.default_rng(52).random((60000,3))
    x=S.sample_rows(a,uniform);y=S.sample_rows(b,uniform)
    assert np.array_equal(x[uniform[:,0]<1/3],y[uniform[:,0]<1/3])
    for indices,sets in [(x,({0,4},{1},{2,3})),(y,({0,4},{1,5},{2,3,6,7,8}))]:
        for rows in sets:assert .32<np.isin(indices,list(rows)).mean()<.35
    assert 4 not in [f[0] for f in b[1]]  # prior-death family creates no boss row


def test_validation_weights_match_stage_family_branch_sampling():
    pools=S.stage_pools([family(1,0,1,[2,3]),family(2,4,5,[6])])
    w=S.state_weights(pools)
    assert abs(sum(w.values())-1)<1e-12
    assert w[0]==w[4]==w[1]==w[5]==1/6
    assert w[2]==w[3]==1/12 and w[6]==1/6


def test_validation_loss_matches_independent_pair_difference_expectation():
    families=[family(1,0,1,[2,3]),family(2,4,5,[6])]
    states=[dict(candidates=[0,1],targets=[int(i%2==0),0]) for i in range(7)]
    values=[[.1*i,.2*i] for i in range(7)]
    class Store:
        def logits(self,model,rows,all_menu):
            return torch.tensor([v for i in rows for v in values[i]]),np.arange(0,2*len(rows)+1,2),None
    actual=S.validation_loss(None,Store(),states,families)
    def loss(i):
        target=states[i]['targets'];q=values[i]
        return ((q[0]-q[1])-(target[0]-target[1]))**2/4
    expected=((loss(0)+loss(4))/2+(loss(1)+loss(5))/2+((loss(2)+loss(3))/2+loss(6))/2)/3
    assert abs(actual-expected)<1e-7


def test_appending_sparse_rows_preserves_the_old_prefix(tmp_path):
    old=S.R.T.Builder();old.append([(0,.3),(4,2.)],8);old.append([(7,-.1)],8);old.save(tmp_path,'shared')
    new=S.cloned_builder(tmp_path,'shared');new.append([(1,.7)],8)
    assert list(new.ptr[:len(old.ptr)])==list(old.ptr)
    assert list(new.cols[:len(old.cols)])==list(old.cols)
    assert list(new.values[:len(old.values)])==list(old.values)
    assert new.ptr[-1]==old.ptr[-1]+1
