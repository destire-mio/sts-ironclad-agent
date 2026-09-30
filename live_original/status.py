"""Small read-only progress snapshot for the ongoing original-game batch."""
import collections,json,shutil,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
rows=[]
for p in [*(HERE/'pilot').glob('*/result.json'),*(HERE/'cohort').glob('*/result.json')]:
    try:rows.append(json.loads(p.read_text()))
    except json.JSONDecodeError:pass
cloud={r['seed']:r for r in json.loads((HERE/'cloud-reference.json').read_text())['rows']}
done=[r for r in rows if r['status'] in ('win','loss','act3_only')]
paired=collections.Counter((r['status']=='win',cloud[r['seed']]['win']) for r in done)
progress=json.loads((HERE/'cohort/progress.json').read_text())
active={}
for seed in progress['active']:
    p=HERE/'cohort'/f'{seed}.log'
    line=p.read_text().splitlines()[-1:] if p.exists() else []
    try:
        d=json.loads(line[0]);active[seed]={k:d[k] for k in ('status','floor','hp','screen','step') if k in d}
    except (ValueError,IndexError):active[seed]='starting or traceback'
print(json.dumps(dict(statuses=dict(collections.Counter(r['status'] for r in rows)),
    complete_pairs=len(done),original_wins=sum(r['status']=='win' for r in done),
    paired_simulator_wins=sum(cloud[r['seed']]['win'] for r in done),
    original_only=paired[True,False],simulator_only=paired[False,True],
    free_gb=round(shutil.disk_usage(HERE).free/1e9,2),pending=len(progress['pending']),active=active),ensure_ascii=False))
if '--faults' in sys.argv:
    for r in sorted(rows,key=lambda r:r['seed']):
        if r['status']=='fault':print(r['seed'],r.get('error'))
