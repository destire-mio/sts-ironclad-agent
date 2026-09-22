from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_exact_control as F


def test_later_branch_changes_its_action_weights_but_not_identical_prefixes():
    store=SimpleNamespace(edges=4,edge_state=np.array([0,0,1,1]))
    weights=F.GraphWeights(store,np.array([.7,.7]),np.array([.7,.7,0.,1.]),[dict(edge_begin=0,edge_end=4)])
    actual=weights([0,1,2,3]).numpy()
    np.testing.assert_allclose(actual,[1.,1.,np.exp(-7),np.exp(3)],rtol=1e-6)
    assert actual[3]/actual[2]>20000


def test_outer_family_cannot_supply_training_labels_or_negative_indices():
    store=SimpleNamespace(edges=4,edge_state=np.array([0,0,1,1]))
    weights=F.GraphWeights(store,np.array([.5,.7]),np.array([0.,1.,0.,1.]),[dict(edge_begin=0,edge_end=2)])
    assert len(weights([0,1]))==2
    with pytest.raises((RuntimeError,AssertionError,ValueError),match='held family'):weights([0,2])
    with pytest.raises((RuntimeError,AssertionError,ValueError),match='invalid edge'):weights([-1])
