"""Read-only replay of saved simulator actions against original decision roots."""
import argparse,gzip,json
from pathlib import Path
from runner import HERE,RUNTIME,OLD,load_selector
from analyze import record_stream

def main():
    parser=argparse.ArgumentParser();parser.add_argument('seed',type=int);args=parser.parse_args();seed=args.seed
    folder=HERE/('pilot' if seed==3900002000 else 'cohort')/str(seed)
    original=[];roots={};seen=set()
    for step in record_stream(folder,'steps'):
        if step['kind']=='outside' and step['decision'] not in seen:
            seen.add(step['decision']);original.append(dict(floor=step['before']['game']['floor'],bits=step['action_bits'],step=step['index']))
        if step['kind']=='combat':roots.setdefault(step['before']['game']['floor'],step['before'])
    path=next((HERE/'simulator/traces').glob(str(seed)+'-*.json.gz'))
    with gzip.open(path,'rt') as f:episode=json.load(f)
    P,_=load_selector();x,parent=P.runtime();C=P.C;S=C.sts
    from sim_patch.parity.adapter import Comparator
    compare=Comparator(RUNTIME/'engine',OLD)
    gc=S.GameContext(S.CharacterClass.IRONCLAD,seed,20);outside=[];battles=[]
    for row in episode['prefix']:
        x.R.clock_input(gc,x.config)
        if row['kind']=='outside':
            outside.append(dict(floor=int(gc.floor_num),bits=row['action']))
            S.GameAction(row['action']&0xffffffff).execute(gc)
        else:
            b=S.BattleContext();b.init(gc);floor=int(gc.floor_num)
            if floor in roots:
                diff=compare.compare_battle(roots[floor],b)['differences']
                battles.append(dict(floor=floor,differences=diff))
            for bits in row['actions']:S.SearchAction.from_bits(bits&0xffffffff).execute(b)
            b.exit_battle(gc)
    first=None
    for i,(a,b) in enumerate(zip(original,outside)):
        if a['floor']!=b['floor'] or a['bits']!=b['bits']:
            first=dict(index=i,original=a,simulator=b);break
    result=dict(seed=seed,original_outside_decisions=len(original),simulator_outside_decisions=len(outside),
        first_outside_action_difference=first,battles=battles)
    out=HERE/f'trajectory-{seed}.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(dict(seed=seed,first_outside_action_difference=first,
        divergent_battle_roots=[dict(floor=b['floor'],paths=[d['path'] for d in b['differences']][:12]) for b in battles if b['differences']]),ensure_ascii=False))

if __name__=='__main__':main()
