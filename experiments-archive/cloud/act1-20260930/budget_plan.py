import gzip,json
from pathlib import Path
O=Path(__file__).resolve().parent
rows=[json.loads(l) for l in gzip.open(O/'fatal-decisions.jsonl.gz','rt')]
assert len(rows)==201 and not any(r['error'] for r in rows)
jobs=[]
for r in rows:
 z=r['steps'][-1];assert z['kind']=='battle' and not z['won']
 jobs.append(dict(seed=r['seed'],index=z['index'],floor=z['before']['floor'],encounter=z['before']['encounter'],sample='all201fatal'))
(O/'budget-fatal-plan.json').write_text(json.dumps(jobs,indent=2))
