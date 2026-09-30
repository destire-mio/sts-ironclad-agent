"""Freeze bridge code and run a bounded cohort; faults never become losses."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.core import sha256,write_json,read_json


def run(args):
    if not 1<=args.workers<=3:raise ValueError('at most three simulator decision processes')
    seeds=args.seeds or list(range(args.first_seed,args.first_seed+args.games))
    if args.replay_prefix and len(seeds)!=1:raise ValueError('a replay prefix belongs to one seed')
    if len(seeds)!=len(set(seeds)):raise ValueError('duplicate natural seeds')
    args.out.mkdir(parents=True,exist_ok=False)
    code=args.out/'code'
    paths=set()
    for pattern in ('steam/*.py','steam/native/*','steam/state_export_mod/src/steamstateexport/*.java',
                    'sim_patch/parity/*.py','sim_patch/parity/java/*.java','sim_patch/alignment/tests/*.py'):
        paths.update(p for p in ROOT.glob(pattern) if p.is_file())
    hashes={}
    for path in sorted(paths):
        target=code/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        hashes[str(path.relative_to(ROOT))]=sha256(target)
    manifest=dict(seeds=seeds,workers=args.workers,
        runtime=str(args.runtime),runtime_manifest_sha256=sha256(args.runtime/'live-manifest.json'),
        code=hashes,arm='sims32+boss12+rest+reuse+svsel+svcard',simulations=32000,
        per_run_timeout_seconds=args.timeout,reload_on_hp_shortfall=args.reload_on_hp_shortfall,
        max_reloads_per_battle=args.max_reloads_per_battle)
    if args.replay_prefix:
        manifest['replay_prefix']=dict(source=str(args.replay_prefix.resolve()),
            result_sha256=sha256(args.replay_prefix/'result.json'))
    write_json(args.out/'manifest.json',manifest)
    active={};pending=list(manifest['seeds']);finished=[];terminated={}
    spec=importlib.util.spec_from_file_location('live_batch_oracle_owner',args.oracle/'run.py')
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    def cleanup(seed):
        instance=args.out/str(seed)/'original/instance'
        if not instance.exists():return
        remaining=owner.instance_processes(instance)
        if remaining:
            owner.stop(instance,force=True)
            write_json(args.out/f'{seed}-orphan-cleanup.json',dict(before=remaining,remaining=owner.instance_processes(instance)))
    try:
        while pending or active:
            while pending and len(active)<args.workers:
                seed=pending.pop(0);directory=args.out/str(seed);log=(args.out/(str(seed)+'.log')).open('w')
                command=[sys.executable,str(code/'steam/live_run.py'),'--runtime',str(args.runtime),
                    '--oracle',str(args.oracle),'--out',str(directory),'--seed',str(seed),
                    '--reload-on-hp-shortfall',str(args.reload_on_hp_shortfall),
                    '--max-reloads-per-battle',str(args.max_reloads_per_battle)]
                if args.replay_prefix:command+=['--replay-prefix',str(args.replay_prefix.resolve())]
                env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','ALIGNMENT_COMPACT_RECORDS':'1',
                     'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
                process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
                active[seed]=(process,log,time.monotonic())
                write_json(args.out/f'{seed}-process.json',dict(pid=process.pid,command=command))
                write_json(args.out/'progress.json',dict(finished=finished,active=list(active),pending=pending))
            for seed,(process,log,started) in list(active.items()):
                expired=time.monotonic()-started>args.timeout
                if expired and process.poll() is None:
                    if seed not in terminated:
                        os.killpg(process.pid,signal.SIGTERM);terminated[seed]=time.monotonic()
                    elif time.monotonic()-terminated[seed]>30:os.killpg(process.pid,signal.SIGKILL)
                code_value=process.poll()
                if code_value is None:continue
                log.close();del active[seed]
                cleanup(seed)
                result_path=args.out/str(seed)/'result.json'
                result=read_json(result_path) if result_path.exists() else dict(status='fault',error='worker exited without result')
                if code_value or result.get('status')=='running':
                    result.update(status='fault',completed_natural_runs=0,worker_exit_code=code_value,
                                  worker_timeout=expired)
                    write_json(result_path,result)
                row=dict(seed=seed,exit_code=code_value,status=result['status'],
                    completed=result.get('completed_natural_runs',0),floor=result.get('floor'),
                    divergences=len(result.get('divergences',[])),save_load_count=result.get('save_load_count',0))
                finished.append(row);write_json(args.out/'progress.json',dict(finished=finished,active=list(active),pending=pending))
                print(json.dumps(row),flush=True)
            time.sleep(.2)
    finally:
        for seed,(process,log,_) in active.items():
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=30)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
            log.close()
            cleanup(seed)
            result_path=args.out/str(seed)/'result.json'
            result=read_json(result_path) if result_path.exists() else {}
            result.update(status='interrupted',completed_natural_runs=0,worker_exit_code=process.returncode)
            write_json(result_path,result)
        if active:write_json(args.out/'interrupted.json',dict(active=list(active),pending=pending,finished=finished))
    completed=[r for r in finished if r['completed']]
    result=dict(status='complete' if len(completed)==len(seeds) else 'faults',
        completed=len(completed),wins=sum(r['status']=='win' for r in completed),
        losses=sum(r['status']=='loss' for r in completed),faults=[r['seed'] for r in finished if not r['completed']],runs=finished)
    write_json(args.out/'summary.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',type=Path,required=True);p.add_argument('--oracle',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,default=3)
    p.add_argument('--first-seed',type=int,default=5100000000);p.add_argument('--games',type=int,default=20)
    p.add_argument('--seeds',type=int,nargs='+',help='explicit seeds for a separate, newly frozen retry cohort')
    p.add_argument('--replay-prefix',type=Path)
    p.add_argument('--reload-on-hp-shortfall',type=int,default=0);p.add_argument('--max-reloads-per-battle',type=int,default=1)
    p.add_argument('--timeout',type=int,default=3600)
    args=p.parse_args()
    for name in ('runtime','oracle','out'):setattr(args,name,getattr(args,name).resolve())
    result=run(args)
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(0 if result['status']=='complete' else 2)
