"""Original-Java Runic Dome export/search regression; never a natural sample."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.core import write_json,sha256
from sim_patch.parity.oracle import Original
from steam.live_search import LiveSearch
from steam.rng_preflight import seed_token


def run(a):
    search=LiveSearch(a.runtime,ROOT,1000)
    rows=[]
    with Original(a.oracle,a.out/'original',ROOT) as original:
        original.call('command',command='start ironclad 20 '+seed_token(5100000002))
        for encounter in ('Chosen','3 Byrds'):
            view=original.call('fixture',encounter=encounter,relic='Runic Dome',
                               hand=['Bash','Strike_R','Defend_R'])
            for m,raw in zip(view['game']['combat_state']['monsters'],view['parity']['raw_state']['monsters']):
                assert m['intent']=='NONE'
                assert m['move_id']==raw['fields']['AbstractMonster.nextMove']>=0
            plan=search.replan(view)
            assert plan['actions']
            action,command=search.next_action(view)
            after=original.call('command',command=command)
            comparison=search.accept(action,after)
            assert not comparison['differences'],comparison['differences']
            write_json(a.out/(encounter.replace(' ','_')+'.json.gz'),dict(before=view,after=after,command=command,plan=plan,comparison=comparison))
            rows.append(dict(encounter=encounter,passed=True,command=command))
    result=dict(passed=True,cases=rows,completed_natural_runs=0,runtime_manifest_sha256=sha256(a.runtime/'live-manifest.json'))
    write_json(a.out/'result.json',result);print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('runtime','oracle','out'):p.add_argument('--'+key,type=Path,required=True)
    run(p.parse_args())
