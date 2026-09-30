"""Let the current games finish, then lower dispatcher concurrency without replay."""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path
from batch import compact,HERE

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    owner=json.loads((HERE/'batch-paused-for-drain.json').read_text())['pid']
    while True:
        rows=subprocess.check_output(['ps','-Ao','pid=,ppid=,state=,command='],text=True).splitlines()
        active=[]
        for line in rows:
            parts=line.strip().split(None,3)
            if len(parts)==4 and int(parts[1])==owner and 'runner.py' in parts[3] and 'Z' not in parts[2]:active.append(int(parts[0]))
        for result in (HERE/'cohort').glob('*/result.json'):
            d=result.parent
            if (d/'original/cleanup.json').exists() and not (d/'archive.json').exists():
                compact(d);print(json.dumps(dict(compacted=d.name)),flush=True)
        if not active:break
        time.sleep(5)
    os.kill(owner,signal.SIGTERM);os.kill(owner,signal.SIGCONT)
    for _ in range(20):
        try:os.kill(owner,0)
        except ProcessLookupError:break
        time.sleep(1)
    print('Restarting dispatcher at '+str(args.workers)+' workers',flush=True)
    result=subprocess.run([sys.executable,str(HERE/'batch.py'),'--games','100','--workers',str(args.workers)],
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    raise SystemExit(result.returncode)

if __name__=='__main__':main()
