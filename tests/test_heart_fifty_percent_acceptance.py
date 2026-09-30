"""Acceptance-contract checks; no policy training or native game is run."""
import copy
import gzip
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import pytest
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_fifty_percent_acceptance as A


def comparisons(wins,net,p):
    return {name:dict(families=128,wins=wins,net=net,p=p) for name in ('parent','initial')}


def development():
    report=dict(status='complete',adoption_gate=dict(monte_carlo=True,temporal=False),
                comparisons=dict(monte_carlo=comparisons(32,12,.0005),temporal=comparisons(20,0,1.)))
    return report,dict(copy.deepcopy(report),unresolved_faults=0)


def test_empirical_goal_requires_full_denominator_and_all_winner_replans():
    assert A.verdict(1024,512,512,0)
    assert not A.verdict(1024,511,511,0)
    assert not A.verdict(1024,103,103,0)
    assert not A.verdict(1023,512,512,0)
    assert not A.verdict(1024,512,511,0)
    assert not A.verdict(1024,512,512,1)


def test_candidate_selection_requires_completed_consistent_paired_admission():
    report,review=development()
    assert A.choose_arm(report,review)=='monte_carlo'
    review['status']='running'
    with pytest.raises(ValueError,match='incomplete'):A.choose_arm(report,review)
    report,review=development()
    for item in (report,review):item['adoption_gate']['temporal']=True
    with pytest.raises(ValueError,match='paired results'):A.choose_arm(report,review)
    report,review=development()
    for item in (report,review):
        item['comparisons']['monte_carlo']=comparisons(20,0,1.)
        item['adoption_gate']['monte_carlo']=False
    with pytest.raises(ValueError,match='no admitted candidate'):A.choose_arm(report,review)


def test_candidate_tie_rule_is_declared_before_final_results():
    report,review=development()
    for item in (report,review):
        item['comparisons']['temporal']=comparisons(32,12,.0005)
        item['adoption_gate']['temporal']=True
    assert A.choose_arm(report,review)=='monte_carlo'
    for item in (report,review):item['comparisons']['temporal']['parent']['wins']=33
    assert A.choose_arm(report,review)=='temporal'


def test_unadmitted_preparation_never_draws_or_reserves(tmp_path,monkeypatch):
    source=tmp_path/'development';source.mkdir()
    root=tmp_path/'acceptance';registry=tmp_path/'registry'
    report,review=development();report['status']='training'
    (source/'result.json').write_text(json.dumps(report))
    (source/'artifact-review.json').write_text(json.dumps(review))
    monkeypatch.setattr(A.P,'checked',lambda root: {})
    def forbidden(*args,**kwargs):raise AssertionError('unqualified seed draw')
    monkeypatch.setattr(A,'draw_seeds',forbidden)
    with pytest.raises(ValueError,match='incomplete'):A.prepare(root,source,[],registry)
    assert not root.exists() and not registry.exists()


def test_history_inventory_finds_private_roles_aliases_and_raw_rows(tmp_path):
    seeds=[A.LOW+i for i in range(11)]
    (tmp_path/'roles-private.json').write_text(json.dumps({'fit':seeds[:2],'evaluation':[str(seeds[2])],
        'embedded':json.dumps({'assignment':seeds[3]})}))
    (tmp_path/'episode.jsonl.gz').write_bytes(gzip.compress((json.dumps({'root':seeds[4]})+'\n').encode()))
    np.save(tmp_path/'assignment.npy',np.asarray(seeds[5:7],dtype=np.int64))
    (tmp_path/'run.run').write_text(json.dumps({'seed':A.encode_game_seed(seeds[7])}))
    torch.save({'metadata':{'family':seeds[8]},'weight':torch.zeros(2)},tmp_path/'actor.pt')
    (tmp_path/'old.csv').write_text('family\n'+str(seeds[9]/1e6)+'e6\n')
    with zipfile.ZipFile(tmp_path/'archive.zip','w') as archive:
        archive.writestr('nested/role.json',json.dumps([seeds[10]]))
    report=A.inventory([tmp_path])
    assert report['status']=='complete'
    assert set(seeds)<=set(report['excluded_seeds'])


def test_inventory_does_not_reuse_different_format_parser_or_ignore_unknown(tmp_path):
    raw=b'family = 10000019'
    (tmp_path/'a.txt').write_bytes(raw)
    (tmp_path/'b.json').write_bytes(raw)
    (tmp_path/'opaque.pkl').write_bytes(b'not loaded unsafely')
    with zipfile.ZipFile(tmp_path/'archive.zip','w') as archive:
        archive.writestr('assignments.unknown',b'10000023')
    report=A.inventory([tmp_path])
    assert report['status']=='incomplete'
    assert {Path(row['path']).name for row in report['errors']}=={'b.json','opaque.pkl','archive.zip'}


def test_native_base35_aliases_and_uint64_identity():
    for seed in (0,A.LOW,1034927625,A.HIGH-1,2**64-1):
        text=A.encode_game_seed(seed)
        assert A.decode_game_seed(text)==seed
        assert A.decode_game_seed(text.lower())==seed
        assert A.decode_game_seed(text.replace('N','O'))==seed
    assert A.scalar_candidates(A.LOW+2**64)=={A.LOW}
    assert A.decode_game_seed('invalid seed!') is None


def test_draw_excludes_prior_seeds_and_duplicates():
    numbers=iter((0,0,1,1,2,2,3,4))
    assert A.draw_seeds({A.LOW,A.LOW+3},3,lambda limit:next(numbers))==[A.LOW+1,A.LOW+2,A.LOW+4]


def test_history_seed_inside_a_source_path_is_excluded():
    assert 1034927625 in A.object_candidates({'source':'/old/episodes/1034927625.json.gz'})


def test_identical_deployed_policy_cannot_gain_new_identity_from_training_metadata():
    actor=dict(identity={'engine':'fixed'},spec={'width':2},actor_state={'weight':torch.tensor([[.5,.2]])})
    original=A.policy_digest(actor)
    renamed=dict(copy.deepcopy(actor),filename='renamed.pt',optimizer={'steps':999},iteration=7)
    assert A.policy_digest(renamed)==original
    renamed['actor_state']['weight'][0,0]=.6
    assert A.policy_digest(renamed)!=original


def test_interrupted_execution_keeps_all_1024_assigned_families(tmp_path):
    jobs=[dict(output=str(tmp_path/'episodes'/str(i))) for i in range(1024)]
    A.P.put(tmp_path/'execution/acceptance/assignments.json',jobs)
    A.P.put(Path(jobs[0]['output'])/'result.json',dict(status='complete',heart=True,simulations=8000))
    A.P.put(Path(jobs[1]['output'])/'result.json',dict(status='fault',simulations=0,cost_incomplete=True))
    result=A.failed_run(tmp_path,TimeoutError('fixture interruption'))
    assert result['assigned_families']==1024 and result['completed_reports']==1
    assert result['fault_reports']==1 and result['families_without_readable_report']==1022
    assert result['reported_wins_pending_review']==1 and result['cost_incomplete']
    assert result['observed_fifty_percent_target_met'] is False


def test_rerunning_an_attempt_does_not_overwrite_its_result(tmp_path,monkeypatch):
    (tmp_path/'execution/acceptance').mkdir(parents=True)
    result=tmp_path/'result.json';result.write_text('{"status":"complete"}')
    original=result.read_bytes()
    with pytest.raises(ValueError,match='attempt exists'):A.run(tmp_path)
    assert result.read_bytes()==original
