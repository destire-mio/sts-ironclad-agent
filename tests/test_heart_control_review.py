"""Check independent review arithmetic and the actual admission boundary."""
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
import heart_offline_control as O


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'docs/experiments'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_numpy_reviewer_matches_nonzero_twin_probabilities_and_actor_logits():
    review=load('e154-review');torch.manual_seed(4);x=torch.randn(17,20)
    twin=O.TwinValue(20);value=O.ProbabilityValue(20);actor=O.Actor(20)
    with torch.no_grad():
        for model in (twin.q1,twin.q2,value,actor):model.tail[-1].weight.normal_(std=.4)
        first,second=twin(x)
        for expected,prefix in [(first,'q1.'),(second,'q2.')]:
            assert np.allclose(expected.numpy(),review.forward(twin.state_dict(),x.numpy(),prefix,True),atol=1e-7)
        assert np.allclose(value(x).numpy(),review.forward(value.state_dict(),x.numpy(),probability=True),atol=1e-7)
        assert np.allclose(actor(x).numpy(),review.forward(actor.state_dict(),x.numpy()),atol=1e-7)


def test_paired_counter_keeps_all_failures_and_zero_discordance():
    review=load('e154-review')
    result=review.paired([0,0,1,1],[0,1,0,1])
    assert result['assigned']==4 and result['net_gain']==0 and result['exact_p']==1
    assert result['paired']==dict(both_fail=1,both_win=1,candidate_only=1,baseline_only=1)
    same=review.paired([0,0,1],[0,0,1])
    assert same['assigned']==3 and same['candidate_wins']==1 and same['paired']==dict(both_fail=2,both_win=1)
