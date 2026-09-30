"""Behavioral checks: original/reuse equivalence, executable witness, isolated input, bad inputs."""
import argparse
import json
import os
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('--reference',action='store_true');parser.add_argument('--sims',type=int,default=2000)
args=parser.parse_args()
if args.reference: os.environ['P300_ENGINE']='arena'
from combat_value_common import C,STUDY,read,put,roots,restore,sha
selected=[]
for stage in ('act2boss','act3boss','heart'):
    selected += [r for r in roots('valid') if r['stage']==stage][:3]
results=[]
for root in selected:
    original=restore(root);unchanged=C.H.fingerprint(original)
    control=C.F.copy_game(original)
    expected=C.F.resolve_reusing(control,args.sims,3.)
    row=dict(root_id=root['id'],actions=expected['actions'],simulations=expected['simulations'],
             outcome=expected['outcome'],fingerprint=C.H.fingerprint(control),stage=root['stage'])
    if not args.reference:
        game=C.F.copy_game(original)
        result=C.value_component().resolve(game,None,'reuse',args.sims,3.)
        assert result['actions']==expected['actions'] and result['simulations']==expected['simulations']
        assert C.H.fingerprint(game)==row['fingerprint']
        assert C.H.fingerprint(original)==unchanged
        # Independently replay the returned plan against the original entry.
        replay=C.F.copy_game(original);battle=C.sts.BattleContext();battle.init(replay)
        for bits in result['actions']: C.sts.SearchAction.from_bits(bits&0xffffffff).execute(battle)
        assert int(battle.outcome)==result['outcome']
        battle.exit_battle(replay);assert C.H.fingerprint(replay)==row['fingerprint']
    results.append(row)
    print(dict(stage=root['stage'],simulations=row['simulations'],mode='reference' if args.reference else 'same-core'),flush=True)
suffix='reference' if args.reference else 'same-core'
put(STUDY/'checks'/f'{suffix}.json',dict(engine_sha256=sha(C.sts.__file__),sims=args.sims,results=results))
if not args.reference:
    assert read(STUDY/'checks/reference.json')['results']==results,'default behavior differs from delivered arena'
    V=C.value_component()
    for sims,mult in ((0,1),(1,0),(-1,1),(1,float('nan'))):
        game=restore(selected[0]);before=C.H.fingerprint(game)
        try: V.resolve(game,None,'reuse',sims,mult)
        except (ValueError,RuntimeError): pass
        else: raise AssertionError('invalid budget accepted')
        assert C.H.fingerprint(game)==before
    z=STUDY/'checks/zero-model.json'
    put(z,dict(schema='combat-value-v1',width=512,hidden=32,w1=[0.]*(512*32),b1=[0.]*32,w2=[0.]*64,b2=[0.]*2))
    net=V.ValueNet(str(z));timed=[]
    for mode in ('reuse','prior','rollout'):
        root=selected[-1];original=restore(root);game=C.F.copy_game(original)
        result=V.resolve(game,net,mode,2000,3.,.05,.01)
        assert result['outcome'] in (int(C.sts.Outcome.PLAYER_VICTORY),int(C.sts.Outcome.PLAYER_LOSS),int(C.sts.Outcome.PLAYER_ESCAPE))
        replay=C.F.copy_game(original);battle=C.sts.BattleContext();battle.init(replay)
        for bits in result['actions']: C.sts.SearchAction.from_bits(bits&0xffffffff).execute(battle)
        battle.exit_battle(replay);assert C.H.fingerprint(replay)==C.H.fingerprint(game)
        assert result['value_evaluations']>0 if mode!='reuse' else result['value_evaluations']==0
        timed.append(dict(mode=mode,seconds=result['seconds'],win=result['win'],value_evaluations=result['value_evaluations']))
    put(STUDY/'checks/summary.json',dict(status='passed',default_pairs=len(results),invalid_budgets=4,
        timed_witnesses=timed,scope='Historical and synthetic correctness checks, not a win-rate comparison.'))
