import copy
import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
H=module('recorded_forks',ROOT/'agent/heart_recorded_forks.py')
V=module('fork_review',ROOT/'docs/experiments/e198-review.py')


def run(actions,status):
    prefix=[];samples=[]
    for i,action in enumerate(actions):
        # Public fingerprints can coincide after different earlier actions.
        prefix.append(dict(kind='outside',before=f'state-{i}',action=action))
        samples.append(dict(active=[0,1],chosen=action,parent=0,base_scores=[0.,0.],probabilities=[.5,.5],
                            features=[[[0,1.],[811,.25]],[[0,1.],[811,.25]]]))
    return dict(prefix=prefix,policy_samples=samples,status=status)


def test_all_branch_points_are_reconstructed_by_both_algorithms():
    rows=[run([0,0],'death'),run([0,1],'heart_win'),run([1,0],'heart_win'),run([1,1],'death')]
    a,shared=H.family_forks(rows);b,other=V.pair_forks(rows)
    assert a==b and shared==other==3 and len(a)==3
    assert sum(n['return_contrast'] for n in a)==2
    assert a[0]['return_contrast'] is False  # balanced branches at the first split
    assert sorted(len(n['members']) for n in a)==[2,2,4]


def test_same_public_state_does_not_merge_different_histories():
    rows=[run([0,0],'death'),run([0,0],'death'),run([1,1],'heart_win'),run([1,1],'heart_win')]
    nodes,shared=H.family_forks(rows)
    assert len(nodes)==1 and nodes[0]['prefix_index']==0 and shared==3
    assert H.family_forks(rows)==V.pair_forks(rows)


def test_source_state_or_menu_disagreement_is_rejected():
    rows=[run([0],'death'),run([1],'heart_win'),run([0],'death'),run([1],'heart_win')]
    for field in ('state','menu'):
        broken=copy.deepcopy(rows)
        if field=='state':broken[1]['prefix'][0]['before']='different-rng'
        else:broken[1]['policy_samples'][0]['base_scores']=[1.,0.]
        with pytest.raises(AssertionError):H.family_forks(broken)
        with pytest.raises(AssertionError):V.pair_forks(broken)


def test_repeated_action_has_empirical_continuation_mean_not_a_certainty_label():
    rows=[run([0,0],'heart_win'),run([0,1],'death'),run([1,0],'death'),run([1,0],'death')]
    nodes,_=H.family_forks(rows);first=nodes[0]
    assert first['actions'][0]['mean_return']==.5 and first['actions'][0]['samples']==2
    assert first['actions'][1]['mean_return']==0 and first['return_contrast']
    assert H.family_forks(rows)==V.pair_forks(rows)


def test_cross_collector_inventory_does_not_pool_return_targets():
    rows=[run([0],'heart_win'),run([1],'death'),run([0],'heart_win'),run([1],'death')]
    rows[1]['policy_samples'][0]['probabilities']=[.2,.8]
    with pytest.raises(AssertionError):H.family_forks(rows)
    a=H.family_forks(rows,compare_returns=False);b=V.pair_forks(rows,compare_returns=False)
    assert a==b and len(a[0])==1
    node=a[0][0];assert node['return_contrast'] is None
    assert all('reward' not in m for m in node['members'])
    assert all('wins' not in m and 'mean_return' not in m for m in node['actions'])
