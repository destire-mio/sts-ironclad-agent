"""Replay-only diagnostic; an undecided continuation is never counted as a win.

Use the same P300_RUNTIME and PYTHONPATH=agent as heart_research.py.
"""
import json
import heart_research as R

path=next((R.OUT/'traj/traj-c38').glob('3900012947-*'))
run,step,g,row=R.root_at(path)
results=[]
for mode in ('recorded','omit_t1_speed','delay_t1_speed_to_t2'):
    b=R.S.BattleContext();b.init(g)
    pending=None;legal=True;events=[]
    for bits in row['actions']:
        a=R.S.SearchAction.from_bits(bits & 0xffffffff)
        if mode=='delay_t1_speed_to_t2' and pending is not None and b.turn==1:
            assert pending.is_valid(b)
            pending.execute(b);pending=None
            events.append('drink delayed Speed at T2 start')
        if not a.is_valid(b):
            legal=False;break
        if b.turn==0 and a.action_type.name=='POTION' and 'Speed Potion' in a.desc(b) and mode!='recorded':
            if mode=='delay_t1_speed_to_t2':pending=a
            events.append('omit original T1 Speed');continue
        a.execute(b)
    results.append(dict(mode=mode,all_recorded_actions_valid=legal,outcome=int(b.outcome),
                        turn=int(b.turn)+1,hp=b.player.cur_hp,heart_hp=b.monsters[0].cur_hp,
                        rng=dict(b.rng_states),potions=R.pots(b.potions),events=events))
print(json.dumps(dict(seed=run['seed'],root=R.C.H.fingerprint(g),results=results),indent=2))
