"""Check the bridge's policy and search against completed production trajectories."""
import gzip, json
from runner import HERE, RUNTIME, ARM, load_selector

def main():
    P,source=load_selector();x,parent=P.runtime();C=P.C;S=C.sts
    import live_combat_search as native
    results=[];boss_checked=False;ordinary_checked=False
    for seed in (3900002000,3900002004,3900002005):
        path=next((HERE/'simulator/traces').glob(str(seed)+'-*.json.gz'))
        with gzip.open(path,'rt') as f:episode=json.load(f)
        gc=S.GameContext(S.CharacterClass.IRONCLAD,seed,20);decisions=0
        for row in episode['prefix']:
            x.R.clock_input(gc,x.config)
            if row['kind']=='outside':
                actions,_,chosen=P.select_live(seed,ARM,[],0,start=gc)
                assert int(actions[chosen].bits)==row['action'],(seed,gc.floor_num)
                actions[chosen].execute(gc);decisions+=1
            else:
                boss=C.is_boss(gc)
                if (boss and not boss_checked) or (not boss and not ordinary_checked):
                    b=S.BattleContext();b.init(gc)
                    expected=C.F.resolve_combat4(C.F.copy_game(gc),40000,12.)
                    actual=native.plan_reusing(b,40000,12.)
                    keys=['actions','simulations','outcome','turns','search_rounds','reused_trees','reused_visits']
                    assert {k:expected[k] for k in keys}=={k:actual[k] for k in keys}
                    assert list(actual['actions'])==row['actions']
                    results.append(dict(seed=seed,floor=gc.floor_num,boss=boss,search_same=True,simulations=actual['simulations']))
                    if boss:boss_checked=True
                    else:ordinary_checked=True
                b=S.BattleContext();b.init(gc)
                for bits in row['actions']:S.SearchAction.from_bits(bits&0xffffffff).execute(b)
                b.exit_battle(gc)
        assert x.R.terminal(gc)==episode['status']
        results.append(dict(seed=seed,policy_decisions_same=decisions,terminal=episode['status']))
    assert ordinary_checked and boss_checked
    (HERE/'selector-extracted.py').write_text(source+'\n')
    (HERE/'binding-check.json').write_text(json.dumps(dict(passed=True,results=results),indent=2))
    print(json.dumps(results))

if __name__=='__main__':main()
