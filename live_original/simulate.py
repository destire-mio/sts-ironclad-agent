"""Same-Mac simulator control, with complete action traces for independent checks."""
import argparse, json, os, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from runner import HERE, RUNTIME, ARM

def one(seed):
    import p300_play as P
    return P.play(seed, ARM+'+traj', [], 0, record_dir=str(HERE/'simulator/traces'))

def main():
    p=argparse.ArgumentParser();p.add_argument('--games',type=int,default=100);p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();out=HERE/'simulator';out.mkdir(exist_ok=True)
    rows=out/'results.jsonl';done=set()
    if rows.exists():done={json.loads(x)['seed'] for x in rows.read_text().splitlines()}
    with ProcessPoolExecutor(args.workers) as pool, rows.open('a') as f:
        jobs=[pool.submit(one,s) for s in range(3900002000,3900002000+args.games) if s not in done]
        for future in as_completed(jobs):
            row=future.result();f.write(json.dumps(row)+'\n');f.flush()
            print(json.dumps(row),flush=True)

if __name__=='__main__':main()
