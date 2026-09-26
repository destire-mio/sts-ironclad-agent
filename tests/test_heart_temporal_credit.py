import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from heart_temporal_credit import temporal_advantages


def test_lambda_one_telescopes_to_complete_return_minus_each_state():
    values=np.array([.2,.6,.4,.8])
    np.testing.assert_allclose(temporal_advantages(values,1,1),1-values,atol=1e-15)
    np.testing.assert_allclose(temporal_advantages(values,0,1),-values,atol=1e-15)


def test_terminal_value_is_zero_and_reward_is_not_repeated():
    np.testing.assert_allclose(temporal_advantages([.2,.6],1,0),[.4,.4])
    np.testing.assert_allclose(temporal_advantages([.2,.6],0,0),[.4,-.6])


def test_temporal_credit_distinguishes_decisions_in_same_losing_game():
    a=temporal_advantages([.2,.8,.1],0,.95)
    assert len(set(np.round(a,10)))==3
    expected=np.array([.6+.95*(-.7+.95*(-.1)),-.7+.95*(-.1),-.1])
    np.testing.assert_allclose(a,expected)


def test_no_cross_episode_bootstrap():
    assert temporal_advantages([.9],0)[0]==-.9
    assert abs(temporal_advantages([.9],1)[0]-.1)<1e-15
