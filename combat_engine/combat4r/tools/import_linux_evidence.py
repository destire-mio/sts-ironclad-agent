from pathlib import Path
import tarfile,json,hashlib
r=Path(__file__).resolve().parents[1];e=r/'evidence';dst=e/'linux-final';dst.mkdir(exist_ok=True)
with tarfile.open(e/'final-cloud-evidence.tar.gz') as tar:
 for m in tar.getmembers():
  assert m.isfile() and Path(m.name).name==m.name
  (dst/m.name).write_bytes(tar.extractfile(m).read())
compact=json.loads((dst/'fixed-compact.json').read_text());issues=[]
for x in compact['q']:
 i=x['position'];a=json.loads((r.parent/'scratchpad/potion2/linux-final'/f'{i:04}.json').read_text())['results']['q']
 expected=hashlib.sha256(json.dumps(a['result'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
 if x['result_sha256']!=expected:issues.append([i,'result'])
 if x['hp']!=a['after']['hp']:issues.append([i,'hp'])
assert len(compact['q'])==432
parallel=json.loads((e/'baseline-parallel-397.json').read_text());assert compact['q'][397]['file_sha256']==parallel['source_sha256']
result=dict(states=432,fields=['full resolver result SHA256','postbattle HP'],issues=issues,parallel_baseline_397_reused=True)
(e/'q-reproduction-linux.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));assert not issues
with tarfile.open(e/'linux-normalized-evidence.tar.gz','w:gz') as tar:
 for p in sorted(dst.iterdir()):tar.add(p,arcname='evidence/linux-final/'+p.name)
 tar.add(e/'q-reproduction-linux.json',arcname='evidence/q-reproduction-linux.json')
