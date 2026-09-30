"""Compare actual visit ratios only where the two games have identical action prefixes."""
import gzip
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load_trace(path):
    with gzip.open(path,'rt') as handle:return json.load(handle)

def main():
    rows=[]
    for seed in range(3900012000,3900014000):
        b=load_trace(next((ROOT/'whole/traj-base').glob(f'{seed}-*.json.gz')))
        n=load_trace(next((ROOT/'whole/traj-fl1').glob(f'{seed}-*.json.gz')))
        ib=inw=0
        for i,(be,ne) in enumerate(zip(b['prefix'],n['prefix'])):
            if be['kind']=='battle' and ne['kind']=='battle':
                bc,nc=b['battles'][ib],n['battles'][inw]
                for key in ['floor','act','hp','max_hp','encounter','deck','relics','potions']:
                    assert bc[key]==nc[key], (seed,i,key)
                rows.append(dict(seed=seed,index=i,act=bc['act'],boss=bc['boss'],encounter=bc['encounter'],
                    base_visits=bc['simulations'],new_visits=nc['simulations'],
                    ratio=nc['simulations']/bc['simulations'],
                    triggered=nc.get('frontload_triggered',False),
                    base_cpu=bc['cpu_seconds'],new_cpu=nc['cpu_seconds'],
                    same_actions=be['actions']==ne['actions'],
                    base_outcome=be['outcome'],new_outcome=ne['outcome']))
                ib+=1;inw+=1
            if be!=ne:break
    target=[r for r in rows if r['act']==1 and not r['boss']]
    result=dict(aligned_battles=len(rows),aligned_eligible_battles=len(target),
                aligned_triggered=sum(r['triggered'] for r in target),
                over_actual_baseline_2x=[r for r in target if r['ratio']>2],
                max_actual_baseline_ratio=max(r['ratio'] for r in target),
                first_divergent_battles=[r for r in rows if not r['same_actions']],
                limitation='Only identical histories are compared. Post-divergence roots have no same-state baseline search in this whole-run experiment.')
    (ROOT/'evidence/aligned-battles.json').write_text(json.dumps(result,indent=2))
    (ROOT/'evidence/aligned-battle-rows.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    print(json.dumps({k:v for k,v in result.items() if k!='first_divergent_battles'},indent=2))

if __name__=='__main__':main()
