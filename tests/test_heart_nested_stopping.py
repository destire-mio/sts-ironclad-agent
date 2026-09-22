import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_nested_stopping as S


def test_stopping_partition_cannot_include_outer_families():
    families=[dict(seed=i,stages=[[i]]) for i in range(300)]
    for held in range(3):
        outer_fit=[f for f in families if S.R.T.fold(f['seed'])!=held]
        fit,valid=S.inner_partition(outer_fit)
        a={f['seed'] for f in fit};b={f['seed'] for f in valid}
        assert not a&b and a|b=={f['seed'] for f in outer_fit}
        assert all(S.R.T.fold(s)!=held for s in a|b)
        assert (fit,valid)==S.inner_partition(outer_fit)


def test_validation_weights_preserve_family_stage_and_branch_balance():
    families=[dict(stages=[[0],[1,2,3,4]]),dict(stages=[[5]])]
    w=S.state_weights(families)
    assert abs(sum(w.values())-1)<1e-12
    assert w[5]==.5 and w[0]==.25 and sum(w[i] for i in (1,2,3,4))==.25


def test_zero_update_model_preserves_parent_without_reading_validation_labels():
    class Store:spec=dict(width=4)
    model,curve,_=S.fit_model(Store(),[],[],48,0)
    assert curve==[]
    x=S.torch.randn(6,4);scores=S.P.with_parent_prior(model(x),S.torch.tensor([2,4]),model.parent_bias)
    assert scores.count_nonzero()==0
