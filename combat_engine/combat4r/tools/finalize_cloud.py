import pathlib,json,subprocess,sys,time,tarfile
r=pathlib.Path(__file__).resolve().parents[1]
while True:
 try:
  rows=[json.loads((r/'evidence/fixed'/f'{i:04}-{mode}.json').read_text()) for mode in ['q','r'] for i in range(432)]
  if all('replay' in x or x.get('error') for x in rows):break
 except (FileNotFoundError,json.JSONDecodeError):pass
 time.sleep(20)
assert all(x.get('error') is None and 'replay' in x for x in rows)
for command in [
 [sys.executable,'tools/summarize_fixed.py','evidence/fixed','evidence/fixed-summary-linux.json'],
 [sys.executable,'tools/summarize_fixed.py','evidence/feed-fixed','evidence/feed-summary-linux.json'],
 [sys.executable,'tools/audit_feed_growth.py','q','../combat4q'],
 [sys.executable,'tools/audit_feed_growth.py','r','../combat4q'],
 [sys.executable,'tools/build_input_identity.py'],
 [sys.executable,'tools/final_audit.py','../combat4q'],
]:subprocess.run(command,cwd=r,check=True)
files=['fixed-summary-linux.json','feed-summary-linux.json','feed-growth-audit-q.json','feed-growth-audit-r.json','feed-all-summary-q.json','feed-all-summary-r.json','build-input-identity.json','final-audit.json','fixed-compact.json','feed-fixed-compact.json','card-audit-validation.json','smoke-summary.json','cloud-driver-insertion.json']
with tarfile.open(r/'evidence/final-cloud-evidence.tar.gz','w:gz') as tar:
 for name in files:tar.add(r/'evidence'/name,arcname=name)
print('cloud final audit completed',flush=True)
