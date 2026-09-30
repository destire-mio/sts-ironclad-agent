"""One explicitly selected simulator diagnostic; never a second original attempt."""
import argparse,json
from simulate import one,HERE

def main():
    p=argparse.ArgumentParser();p.add_argument('seed',type=int);a=p.parse_args()
    out=HERE/'simulator/results.jsonl'
    prior=[json.loads(line) for line in out.read_text().splitlines()]
    if any(r['seed']==a.seed for r in prior):raise ValueError('simulator result already exists')
    trace=list((HERE/'simulator/traces').glob(str(a.seed)+'-*.json.gz'))
    if trace:raise ValueError('existing diagnostic trace; inspect it before starting another run')
    row=one(a.seed)
    with out.open('a') as f:f.write(json.dumps(row)+'\n')
    print(json.dumps(row),flush=True)

if __name__=='__main__':main()
