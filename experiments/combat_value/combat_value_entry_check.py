"""P300 arm exclusivity and live entry routing, without starting a complete game."""
import os
from combat_value_common import C,STUDY,roots,restore,put
os.environ['P300_VALUE_MODEL']=str(STUDY/'model/value.json')
import p300_play as P

if __name__=='__main__':
    conflicts=['valuenet+reuse','valuenet+fast','valuenet+adapt2','valuenet+refine']
    for arm in conflicts:
        try: P.play(1,arm,[],500)
        except ValueError as exc: assert 'separate search policies' in str(exc)
        else: raise AssertionError('conflicting arm accepted: '+arm)
    rows=[]
    for mode in ('prior','rollout'):
        os.environ['P300_VALUE_MODE']=mode
        r=next(r for r in roots('valid') if r['stage']=='heart')
        game=restore(r);direct=C.F.copy_game(game)
        out=C.resolve_value(game,1000,3.)
        expected=C.value_component().resolve(direct,C._VALUE_MODEL,mode,1000,3.)
        assert out['actions']==expected['actions'] and out['simulations']==expected['simulations']
        assert C.H.fingerprint(game)==C.H.fingerprint(direct)
        rows.append(dict(mode=mode,value_evaluations=out['value_evaluations'],simulations=out['simulations']))
    r=roots('valid')[0];run=C.read_run(r['path'])
    for index,game in C.battle_states(run):
        if int(game.act)==1 and not C.is_boss(game):
            a=C.F.copy_game(game);b=C.F.copy_game(game)
            value=C.resolve_value(a,1000,3.);reuse=C.F.resolve_reusing(b,1000,3.)
            assert value['actions']==reuse['actions'] and C.H.fingerprint(a)==C.H.fingerprint(b)
            break
    else: raise AssertionError('non-target natural battle missing')
    put(STUDY/'checks/p300-entry.json',dict(status='passed',conflicts=conflicts,target_modes=rows,
         non_target_reuse=True,full_games=0,evidence='entry correctness, not a win-rate comparison'))
