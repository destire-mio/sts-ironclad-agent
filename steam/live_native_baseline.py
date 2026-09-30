"""Same-seed native reference using the frozen, unchanged P300 play function."""
import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.core import write_json,sha256
from steam.live_search import LiveSearch
from steam.live_policy import LivePolicy,functions_from


def run(a):
    a.out.mkdir(parents=True,exist_ok=False)
    search=LiveSearch(a.runtime,ROOT);policy=LivePolicy(search,a.first_seed)
    source=a.runtime/'p300/agent/p300_play.py'
    teacher=functions_from(a.runtime/'p300/agent/p300_teacher.py',['deck_key','deck_delta'],{})
    common=SimpleNamespace(sts=policy.sts,F=policy.F,
        is_boss=lambda g:policy.F.is_boss(int(g.encounter)),
        summary=lambda g:dict(floor=g.floor_num,act=g.act,hp=g.cur_hp,max_hp=g.max_hp,encounter=g.encounter.name))
    runtime=SimpleNamespace(R=policy.R,A=policy.A,config=json.loads((a.runtime/'config.json').read_text()))
    original=functions_from(source,['play','sv_choice','teacher_indices','pre_boss_rest'],
                            dict(C=common,T=teacher,runtime=lambda:(runtime,policy.parent),time=time))
    write_json(a.out/'manifest.json',dict(seeds=list(range(a.first_seed,a.first_seed+a.games)),
        runtime_manifest_sha256=sha256(a.runtime/'live-manifest.json'),p300_play_sha256=sha256(source),
        scope='unmodified frozen P300 play; one simulator decision process'))
    rows=[]
    for seed in range(a.first_seed,a.first_seed+a.games):
        row=original.play(seed,'sims32+boss12+rest+reuse+svsel+svcard',[],0)
        write_json(a.out/f'{seed}.json',row);rows.append(row)
        print(json.dumps(row),flush=True)
    write_json(a.out/'summary.json',dict(runs=rows,wins=sum(r['win'] for r in rows),
        completed=sum(r['status'] in ('heart_win','death','act3_without_heart') for r in rows)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('runtime','out'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--first-seed',type=int,default=5100000000);p.add_argument('--games',type=int,default=20)
    a=p.parse_args();a.runtime=a.runtime.resolve();run(a)
