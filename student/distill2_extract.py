"""Replay recorded actions; label the reconstructed states with the complete teacher."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import gzip
import importlib
import json
from pathlib import Path
import traceback
import torch
from distill2_base import sha,decision_type
from distill2_features import schema_from_runtime,public_packet
from distill2_teacher import DEFAULT_ARMS,teacher_function,label_copy
from distill2_data import Writer


def extract_job(job):
    paths,output,module,arms,schema,relabel=job
    torch.set_num_threads(1)
    P=importlib.import_module(module);x,parent=P.runtime();sts=x.R.sts
    oracle=teacher_function(P,arms);writer=Writer();audits=[]
    for path in paths:
        audit=dict(path=path,sha256=sha(path),status='failed')
        try:
            run=json.load(gzip.open(path,'rt'));seed=run['seed'];audit['seed']=seed
            assert not run['error'] and run['status'] in ('heart_win','death','act3_without_heart')
            if not relabel: assert set(run['arm'].split('+'))-{'traj'}==set(arms.split('+'))
            gc=sts.GameContext(sts.CharacterClass.IRONCLAD,seed,20)
            groups=[];bosses=[];battles=combat_actions=changed=0
            for step,row in enumerate(run['prefix']):
                x.R.clock_input(gc,x.config)
                if 'before' in row: assert x.R.fingerprint(gc)==row['before'],'fingerprint mismatch'
                if row['kind']=='battle':
                    assert gc.screen_state==sts.ScreenState.BATTLE
                    entry=P.C.summary(gc);boss=P.C.is_boss(gc)
                    bc=sts.BattleContext();bc.init(gc)
                    for bits in row['actions']:
                        action=sts.SearchAction.from_bits(bits & 0xffffffff)
                        assert action.is_valid(bc),'illegal combat action'
                        action.execute(bc);combat_actions+=1
                    assert int(bc.outcome)==row['outcome'],'battle result mismatch'
                    bc.exit_battle(gc);battles+=1
                    if boss:bosses.append(dict(entry,won=gc.outcome!=sts.GameOutcome.PLAYER_LOSS,hp_after=int(gc.cur_hp)))
                else:
                    assert gc.screen_state!=sts.ScreenState.BATTLE
                    acts=list(sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc)
                    bits=[int(a.bits) for a in acts];recorded=bits.index(row['action'])
                    label=label_copy(P,x,parent,oracle,gc,acts,seed)
                    changed+=label!=recorded
                    if not relabel: assert label==recorded,f'final teacher label mismatch step {step}: {label} vs {recorded}'
                    packet=public_packet(gc,acts,ds,schema,x.A)
                    groups.append((packet,dict(seed=seed,step=step,floor=int(gc.floor_num),act=int(gc.act),
                        label=label,recorded_label=recorded,type=decision_type(gc,x.A,ds))))
                    assert acts[recorded].is_valid(gc);acts[recorded].execute(gc)
            terminal=dict(status=x.R.terminal(gc),floor=int(gc.floor_num),act=int(gc.act),hp=int(gc.cur_hp),max_hp=int(gc.max_hp))
            assert all(run[k]==v for k,v in terminal.items()),f'terminal mismatch {terminal}'
            assert bosses==run['bosses'],'boss summaries mismatch'
            for packet,meta in groups:writer.add(packet,**meta)
            audit.update(status='passed',outside=len(groups),teacher_checks=len(groups),changed=changed,
                         battles=battles,combat_actions=combat_actions,terminal=terminal,
                         before_checks=sum('before' in r for r in run['prefix']),final_fingerprint=x.R.fingerprint(gc))
        except Exception:audit['error']=traceback.format_exc()
        audits.append(audit)
    writer.save(output)
    Path(output+'.audit.json').write_text(json.dumps(audits,indent=2))
    return dict(shard=output,total=len(paths),passed=sum(r['status']=='passed' for r in audits),
                decisions=len(writer.meta['seed']),candidates=writer.offsets[-1],
                errors=[r for r in audits if r['status']!='passed'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--trajectory-dirs',nargs='+',required=True)
    p.add_argument('--output',required=True);p.add_argument('--teacher-module',default='p300_play_v21')
    p.add_argument('--arms',default=DEFAULT_ARMS);p.add_argument('--workers',type=int,default=7)
    p.add_argument('--shard-size',type=int,default=20);p.add_argument('--limit',type=int)
    p.add_argument('--relabel',action='store_true');a=p.parse_args()
    assert 1<=a.workers<=7
    torch.set_num_threads(1)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    P=importlib.import_module(a.teacher_module);x,parent=P.runtime();schema=schema_from_runtime(x,parent)
    paths=sorted(str(p) for d in a.trajectory_dirs for p in Path(d).glob('*.json.gz'))
    if a.limit:paths=paths[:a.limit]
    seeds=[int(Path(p).name.split('-')[0]) for p in paths]
    assert paths and len(seeds)==len(set(seeds))
    assert all(3900012000<=s<3900014000 or 3900018000<=s<3900019000 for s in seeds),'unexpected training block'
    from distill2_provenance import identity,bind
    manifest=dict(identity=identity(P,x),arms=a.arms,paths={p:sha(p) for p in paths},
                  seeds=seeds,split='seed%10: 0=test 1=validation 2..9=train',relabel=a.relabel)
    bind(out/'manifest.json',manifest)
    (out/'schema.json').write_text(json.dumps(schema,indent=2))
    (out/'teacher-extracted.py').write_text(teacher_function(P,a.arms).extracted_source)
    base=parent
    while hasattr(base,'base'):base=base.base
    if not (out/'parent-net.pt').exists():torch.save(base.net.state_dict(),out/'parent-net.pt')
    jobs=[];results=[]
    for i in range(0,len(paths),a.shard_size):
        dest=str(out/f'shard-{i//a.shard_size:04d}.npz'); receipt=Path(dest+'.receipt.json')
        if receipt.exists():
            results.append(json.loads(receipt.read_text()));continue
        if Path(dest+'.started').exists():raise RuntimeError('interrupted shard; preserve it, no automatic retry: '+dest)
        jobs.append((paths[i:i+a.shard_size],dest,a.teacher_module,a.arms,schema,a.relabel))
    with ProcessPoolExecutor(a.workers) as pool:
        futures=[]
        for j in jobs:
            Path(j[1]+'.started').write_text('scheduled\n');futures.append(pool.submit(extract_job,j))
        for f in as_completed(futures):
            r=f.result();results.append(r)
            Path(r['shard']+'.receipt.json').write_text(json.dumps(r,indent=2))
            print(json.dumps(r),flush=True)
    (out/'summary.json').write_text(json.dumps(results,indent=2))
    if any(r['passed']!=r['total'] for r in results):raise SystemExit('replay failed; training blocked')


if __name__=='__main__':main()
