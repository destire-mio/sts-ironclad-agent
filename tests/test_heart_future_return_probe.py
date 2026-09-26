"""Guard the discovery/confirmation boundary and the no-change tie rule."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from heart_future_return_probe import decision_metrics


def records(seed,discovery,confirmation):
    return [dict(seed=seed,world_index=i,gain=g)
            for i,g in enumerate(discovery+confirmation)]


def test_confirmation_cannot_change_selected_action():
    assignments=[dict(row=dict(seed=1,delta=1))]
    favorable=decision_metrics(assignments,records(1,[1]*8,[1]*8))
    unfavorable=decision_metrics(assignments,records(1,[1]*8,[-1]*8))
    assert favorable['families'][0]['averaged_select']
    assert unfavorable['families'][0]['averaged_select']
    assert favorable['averaged_confirmation_gain']==1
    assert unfavorable['averaged_confirmation_gain']==-1


def test_zero_discovery_gain_keeps_parent_despite_original_rescue():
    assignments=[dict(row=dict(seed=1,delta=1))]
    result=decision_metrics(assignments,records(1,[1,-1]*4,[-1]*8))
    assert not result['families'][0]['averaged_select']
    assert result['original_confirmation_gain']==-1
    assert result['averaged_confirmation_gain']==0
    assert result['confirmation_improvement']==1


def test_families_keep_equal_weight_across_strata():
    assignments=[dict(row=dict(seed=1,delta=1)),dict(row=dict(seed=2,delta=-1))]
    data=records(1,[1]*8,[-1]*8)+records(2,[1]*8,[1]*8)
    result=decision_metrics(assignments,data)
    assert result['assigned_families']==2
    assert result['averaged_confirmation_gain']==0
    assert result['original_confirmation_gain']==-.5
