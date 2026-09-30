"""Bounded, resumable original cohort. An attempted seed is never retried implicitly."""
import argparse, gzip, json, os, shutil, signal, subprocess, sys, time
from pathlib import Path

HERE=Path(__file__).resolve().parent

def compact(out):
    """Retain every record, using compression across successive observations."""
    counts={}
    for pattern,name in [('step-*.json.gz','steps'),('decision-*.json.gz','decisions'),('plan-*.json','plans')]:
        paths=sorted(out.glob(pattern))
        if not paths:continue
        target=out/(name+'.jsonl.gz')
        if target.exists():raise FileExistsError(target)
        with gzip.open(target,'wt',compresslevel=6) as stream:
            for p in paths:
                with gzip.open(p,'rt') if p.suffix=='.gz' else p.open() as f:row=json.load(f)
                stream.write(json.dumps(dict(file=p.name,data=row),separators=(',',':'))+'\n')
        with gzip.open(target,'rt') as stream:assert sum(1 for _ in stream)==len(paths)
        for p in paths:p.unlink()
        counts[name]=len(paths)
    original=out/'original'
    if (original/'cleanup.json').exists():
        cleanup=json.loads((original/'cleanup.json').read_text())
        assert not cleanup['remaining']
        # Remove only disposable immutable copies and generated extraction cache.
        instance=original/'instance'
        for p in [*instance.glob('*.jar'),*instance.glob('mods/*.jar')]:p.unlink()
        if (instance/'tmp').exists():shutil.rmtree(instance/'tmp')
        # RPC and observations duplicate the complete before/after step records.
        # Preserve both streams, but recompress the low-compression RPC stream.
        rpc=original/'rpc.jsonl.gz'
        if rpc.exists():
            temp=rpc.with_suffix('.repack')
            with gzip.open(rpc,'rb') as src,gzip.open(temp,'wb',compresslevel=6) as dst:shutil.copyfileobj(src,dst)
            temp.replace(rpc)
    (out/'archive.json').write_text(json.dumps(dict(counts=counts,immutable_instance_copies_removed=True)))

def main():
    p=argparse.ArgumentParser();p.add_argument('--games',type=int,default=100);p.add_argument('--workers',type=int,default=4)
    p.add_argument('--hours',type=float,default=7.5)
    p.add_argument('--new-session',action='store_true',help='user-invoked continuation with a fresh wall-time budget')
    args=p.parse_args()
    if not 1<=args.workers<=8:raise ValueError('workers must be 1..8')
    root=HERE/'cohort';root.mkdir(exist_ok=True)
    active={};started=time.monotonic();attempted=[]
    deadline=time.time()+args.hours*3600
    if not args.new_session:deadline=min(deadline,json.loads((HERE/'plan.json').read_text())['deadline_unix']-600)
    for seed in range(3900002000,3900002000+args.games):
        prior=HERE/'pilot'/str(seed)
        if (prior/'result.json').exists() or (root/str(seed)/'result.json').exists():continue
        if (root/str(seed)).exists():raise RuntimeError('unfinished prior attempt: '+str(seed))
        attempted.append(seed)
    def terminate(signum,frame):raise KeyboardInterrupt(signum)
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,terminate)
    try:
        while attempted or active:
            limit=args.workers
            control=HERE/'worker-limit.json'
            if control.exists():limit=max(1,min(args.workers,int(json.loads(control.read_text())['workers'])))
            while attempted and len(active)<limit and time.time()<deadline-1800:
                free=shutil.disk_usage(HERE).free
                if free<600_000_000:break
                seed=attempted.pop(0);out=root/str(seed);log=(root/f'{seed}.log').open('w')
                proc=subprocess.Popen([sys.executable,str(HERE/'runner.py'),'--seed',str(seed),'--out',str(out)],
                    stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
                active[seed]=(proc,log,time.monotonic())
                print(json.dumps(dict(event='start',seed=seed,pid=proc.pid)),flush=True)
            for seed,(proc,log,began) in list(active.items()):
                if proc.poll() is None:
                    if time.monotonic()-began>1800 or time.time()>=deadline:proc.terminate()
                    continue
                log.close();out=root/str(seed)
                if (out/'result.json').exists():
                    result=json.loads((out/'result.json').read_text());compact(out)
                else:
                    out.mkdir(exist_ok=True);result=dict(seed=seed,status='fault',error='worker exit '+str(proc.returncode))
                    (out/'result.json').write_text(json.dumps(result))
                print(json.dumps(dict(event='finish',seed=seed,status=result['status'],seconds=time.monotonic()-began)),flush=True)
                del active[seed]
            (root/'progress.json').write_text(json.dumps(dict(pending=attempted,active=list(active),workers=limit,seconds=time.monotonic()-started)))
            if not active and attempted and (shutil.disk_usage(HERE).free<600_000_000 or time.time()>=deadline-1800):break
            time.sleep(1)
    finally:
        for proc,log,_ in active.values():
            if proc.poll() is None:proc.terminate()
        for proc,log,_ in active.values():
            try:proc.wait(timeout=45)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            log.close()
    print(json.dumps(dict(event='batch_exit',pending=len(attempted))),flush=True)

if __name__=='__main__':main()
