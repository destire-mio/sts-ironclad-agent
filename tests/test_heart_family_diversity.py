import copy
import hashlib
from pathlib import Path
import random
import sys
from types import SimpleNamespace as NS

import pytest
import torch

sys.path.insert(0, str(Path(__file__).parents[1]/'agent'))
import heart_family_diversity as H


def test_family_schedule_is_disjoint_hash_selected_and_pool_order_independent():
    pool = list(range(1536)); old = dict(fit=pool[:128], evaluation=pool[128:256])
    roles = H.assign_roles(pool, old)
    assert roles == H.assign_roles(pool[::-1], old)
    expected = sorted(pool[256:], key=lambda s: hashlib.sha256(f'E199-cohort:{s}'.encode()).hexdigest())[:384]
    assert sum(roles['cohorts'][1:], []) == expected
    assert roles['cohorts'][0] == old['fit'] and roles['evaluation'] == old['evaluation']
    assert len(set(sum(roles['cohorts'], []))) == 512
    assert set(sum(roles['cohorts'], [])).isdisjoint(roles['evaluation'])
    broken = copy.deepcopy(old); broken['evaluation'][0] = old['fit'][0]
    with pytest.raises(AssertionError): H.assign_roles(pool, broken)


@pytest.mark.parametrize('role,iteration,index,repeat', [
    ('fit',0,0,0), ('fit',4,0,0), ('fit',1,128,0), ('fit',1,0,4),
    ('fit',True,0,0), ('fit',1,False,0), ('evaluation',0,0,1),
    ('preflight',1,16,0), ('preflight',2,0,0), ('unknown',1,0,0),
])
def test_assignment_rejects_unregistered_work(role,iteration,index,repeat):
    roles = H.assign_roles(list(range(1536)),dict(fit=list(range(128)),evaluation=list(range(128,256))))
    with pytest.raises(AssertionError): H.assignment(roles,role,iteration,index,repeat)
    assert H.assignment(roles,'fit',2,127,3) == roles['cohorts'][2][127]
    assert H.assignment(roles,'evaluation',0,127,0) == roles['evaluation'][127]


class Game:
    def __init__(self, character, seed, ascension):
        assert character == 'IRONCLAD' and ascension == 20
        self.seed = seed; self.history = []


class Action:
    def __init__(self,bits): self.bits = bits
    def is_valid(self,gc): return len(gc.history) < 4


class Policy:
    def __init__(self): self.rng = random.Random(7); self.samples = []
    def choose(self,gc,obs,actions,descriptors):
        uniform = self.rng.random(); chosen = int(uniform >= .5)
        self.samples.append(dict(uniform=uniform,chosen=chosen,before=tuple(gc.history)))
        return chosen


def toy_runtime():
    def fingerprint(gc): return tuple(gc.history)
    def replay(gc,step,config):
        assert step['before'] == fingerprint(gc)
        gc.history.append(step['action'])
    def terminal(gc,reference): assert fingerprint(gc) == reference['terminal_fingerprint']
    def result(gc,prefix):
        return dict(seed=gc.seed,status='death',target=False,error=None,floor=3,act=1,hp=0,
                    keys=[],steps=len(prefix),prefix=prefix,terminal_fingerprint=fingerprint(gc),
                    simulations=8000,samples=['old labels'],roots=['old roots'])
    def reference(actions):
        gc = Game('IRONCLAD',99,20); prefix = []
        for i,action in enumerate([actions[0],95,*actions[1:]]):
            step = dict(kind='battle' if i==1 else 'outside',before=fingerprint(gc),action=action)
            prefix.append(step); replay(gc,step,{})
        return result(gc,prefix)
    def rollout(seed,config,gc,net,record,record_samples):
        assert gc.seed == seed and gc.history == [] and record and not record_samples
        prefix = []
        for i in range(4):
            action = 95 if i==1 else net.choose(gc,[],[Action(0),Action(1)],[])
            step = dict(kind='battle' if i==1 else 'outside',before=fingerprint(gc),action=action)
            prefix.append(step); replay(gc,step,config)
        return result(gc,prefix)
    x = NS(R=NS(sts=NS(GameContext=Game,CharacterClass=NS(IRONCLAD='IRONCLAD'),
                       get_legal_game_actions=lambda gc:[Action(0),Action(1)]),
                clock_input=lambda gc,c:None,fingerprint=fingerprint,replay_step=replay,rollout=rollout),
           A=NS(build_choices=lambda gc:([],[],[]),obs_vec=lambda gc:[]),P=NS(verify_terminal=terminal))
    return x,reference


def test_divergent_probe_resets_game_random_stream_and_samples_before_fresh_rollout():
    x,reference = toy_runtime(); old = reference([0,1,0])
    run,policy,execution = H.collect_route(x,Policy,old,{},True)
    direct,direct_policy,_ = H.collect_route(x,Policy,old,{},False)
    assert run == direct and policy.samples == direct_policy.samples
    assert [s['action'] for s in run['prefix']] == [0,95,0,1]
    assert [s['chosen'] for s in policy.samples] == [0,0,1]
    assert execution == dict(mode='fresh_mcts',first_probe_difference=2)


def test_complete_reuse_records_current_policy_and_discards_old_training_labels():
    x,reference = toy_runtime(); old = reference([0,0,1]); snapshot = copy.deepcopy(old)
    run,policy,execution = H.collect_route(x,Policy,old,{},True)
    direct,direct_policy,_ = H.collect_route(x,Policy,old,{},False)
    assert run['prefix'] == direct['prefix'] and run['terminal_fingerprint'] == direct['terminal_fingerprint']
    assert policy.samples == direct_policy.samples and len(policy.samples) == 3
    assert run['simulations'] == 0 and run['source_search_simulations'] == 8000
    assert run['samples'] == run['roots'] == [] and old == snapshot
    assert execution == dict(mode='reused_whole_reference',first_probe_difference=None)


def test_state_corruption_is_a_fault_not_a_cache_miss():
    x,reference = toy_runtime(); old = reference([0,0,1])
    broken = copy.deepcopy(old); broken['prefix'][2]['before'] = ('bad rng',)
    with pytest.raises(AssertionError): H.collect_route(x,Policy,broken,{},True)
    class MutatingPolicy(Policy):
        def choose(self,gc,*args):
            choice = super().choose(gc,*args); gc.history.append(7); return choice
    with pytest.raises(AssertionError,match='changed state/RNG'):
        H.collect_route(x,MutatingPolicy,old,{},True)


def test_checkpoint_cannot_be_relabelled_as_another_role_registration_or_source(tmp_path):
    (tmp_path/'registration.json').write_text('{}'); (tmp_path/'roles-private.json').write_text('[]')
    x = NS(identity={'engine_sha256':'engine'}); G = NS(RECIPE={'epochs':2},Policy=lambda *a,**k:(a,k))
    path = tmp_path/'actor.pt'; state = {'weight':torch.tensor([.3],dtype=torch.float64)}
    H.save_actor(tmp_path,x,G,state,path,0)
    _,value = H.load_policy(tmp_path,x,G,path,H.F.sha(path),123)
    assert torch.equal(value['actor_state']['weight'],state['weight'])
    for key,bad in [('model_type','whole_policy_gradient'),('roles_sha256','other'),
                    ('registration_sha256','other'),('after_round',4),('after_round',True)]:
        altered = copy.deepcopy(value); altered[key] = bad; torch.save(altered,path)
        with pytest.raises(AssertionError): H.load_policy(tmp_path,x,G,path,H.F.sha(path),123)
