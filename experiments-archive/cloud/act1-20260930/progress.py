import json,collections
from pathlib import Path
O=Path(__file__).resolve().parent
for file in ['extract.log','gate-results.jsonl','budget-fatal-plan-results.jsonl','route-attribution.jsonl','outer-plan-results.jsonl','budget-control-plan-results.jsonl']:
 p=O/file
 if not p.exists():continue
 lines=p.read_text().splitlines()
 if file=='extract.log':print(file,lines[-1:] if lines else []);continue
 rows=[json.loads(l) for l in lines];print(file,'n',len(rows),'errors',sum(bool(r.get('error')) for r in rows))
 if file.startswith('budget'):
  good=[r for r in rows if not r.get('error') and len(r['arms'])==2]
  print('battle rescues',sum(not r['arms'][0]['won'] and r['arms'][1]['won'] for r in good),'lost',sum(r['arms'][0]['won'] and not r['arms'][1]['won'] for r in good),'CPU',round(sum(sum(a['cpu'] for a in r['arms']) for r in good),1))
 if file=='outer-plan-results.jsonl':
  by=collections.defaultdict(list)
  for r in rows:by[r['job']['rule']].append(r)
  print({k:dict(n=len(v),rescued=sum(r.get('rescued',0) for r in v),lost=sum(r.get('lost',0) for r in v)) for k,v in by.items()})
 if any(r.get('error') for r in rows):print(next(r['error'] for r in rows if r.get('error')))
