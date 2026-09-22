import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_control_data as G


def row(actions=(10,20)):
    return dict(observation=[[0,.5]],descriptors=[[[i,1.]] for i in range(len(actions))],
                actions=list(actions),act=1,floor=3)


def raw(seed,steps,target):
    return dict(seed=seed,target=target,terminal_fingerprint='f'*64,
                prefix=[dict(kind='outside',before=s*64,action=a) for s,a in steps])


def source(target,path):
    return dict(scope='fixture',path=path,sha256='x',target=target,forced=[])


def test_shared_prefix_not_multiplied_and_future_intervention_not_terminal_labelled():
    g=G.Graph(7)
    for s in 'abc':g.state(s*64,row(),0)
    g.route(source(0,'lose'),raw(7,[('a',10),('b',10)],0))
    g.route(source(1,'win'),raw(7,[('a',10),('b',20),('c',10)],1))
    first=[e for e in g.edges if e['state']==0]
    assert len(first)==1 and first[0]['reward']==0 and first[0]['next_state']==1
    assert not first[0]['done'] and first[0]['occurrences']==2
    assert [(e['reward'],e['done']) for e in g.edges]==[(0,False),(0,True),(0,False),(1,True)]
    assert g.finish({})['multiple_successor_state_actions']==0


def test_battles_are_inside_transition_and_terminal_loss_is_not_truncation():
    g=G.Graph(8);g.state('a'*64,row(),0);g.state('b'*64,row(),1)
    r=raw(8,[('a',10),('b',20)],0)
    r['prefix'].insert(1,dict(kind='battle',before='c'*64,actions=[9]))
    g.route(source(0,'death'),r)
    assert g.routes[0]['edges']==[[0,0],[2,1]]
    assert g.edges[0]['next_state']==1 and not g.edges[0]['done']
    assert g.edges[1]['next_state'] is None and g.edges[1]['done'] and g.edges[1]['reward']==0


def test_distinct_full_states_cannot_be_spliced_and_encoding_conflicts_reject():
    g=G.Graph(7);g.state('a'*64,row(),0)
    with pytest.raises(KeyError):g.route(source(1,'bad'),raw(7,[('b',10)],1))
    altered=row();altered['observation']=[[0,.6]]
    with pytest.raises(ValueError):g.state('a'*64,altered,0)
    with pytest.raises(ValueError):g.state('a'*64,row(),1)
    with pytest.raises(ValueError):g.route(source(1,'wrong_family'),raw(8,[('a',10)],1))


def test_multiple_successors_preserved_for_inspection_not_silently_averaged():
    g=G.Graph(7)
    for s in 'abc':g.state(s*64,row(),0)
    g.route(source(1,'first'),raw(7,[('a',10),('b',20)],1))
    g.route(source(0,'second'),raw(7,[('a',10),('c',20)],0))
    assert len([e for e in g.edges if e['state']==0])==2
    assert g.finish({})['multiple_successor_state_actions']==1


def test_non_fit_and_cross_boss_card_inputs_rejected():
    state=dict(seed=7,split='fit',id='card',chosen=0,candidates=[0,1],prefix_index=1,
               fingerprint='a'*64,**row())
    node=dict(seed=7,split='fit',state=state,leaves=[dict(candidate=i,target=0,path=str(i),sha256='x') for i in range(2)])
    bad=copy.deepcopy(node);bad['split']='development'
    with pytest.raises(ValueError):G.sources_for(bad,None,{}, {})
    tree=dict(seed=7,boss_root=state,branches=[dict(relic_candidate=1,source_path='boss',source_sha256='b',parent_target=0,card_root='next')])
    wrong=dict(state,relic_candidate=0,source_sha256='b')
    with pytest.raises(ValueError):G.sources_for(node,tree,{'next':wrong},{})
