from pathlib import Path
import json
r=Path(__file__).resolve().parents[1];s=r/'snapshots/card-audit';p=r/'evidence/probes'
source=(s/'analyze.py').read_text();start=source.index('expected={}',source.index('probes ='));end=source.index('assert set(expected)',start);env={};exec(source[start:end],env);expected=env['expected']
rows={x['name']:x for x in map(json.loads,(p/'mechanism_probe-r.jsonl').read_text().splitlines())}
assert set(rows)==set(expected)
diff={n:{k:{'expected':v,'actual':rows[n][k]} for k,v in x.items() if rows[n][k]!=v} for n,x in expected.items()};diff={k:v for k,v in diff.items() if v}
source=(s/'verify_status.py').read_text();start=source.index('expected={}');end=source.index('assert set(rows)',start);env={};exec(source[start:end],env);expected2=env['expected']
rows2={x['name']:x for x in map(json.loads,(p/'status_probe-r.jsonl').read_text().splitlines())};assert set(rows2)==set(expected2)
diff2={n:{k:{'expected':v,'actual':rows2[n][k]} for k,v in x.items() if rows2[n][k]!=v} for n,x in expected2.items()};diff2={k:v for k,v in diff2.items() if v}
result=dict(mechanism_cases=len(rows),mechanism_differences=diff,status_cases=len(rows2),status_differences=diff2,scalar_checks=sum(map(len,expected.values()))+sum(map(len,expected2.values())))
(r/'evidence/card-audit-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));assert not diff and not diff2
