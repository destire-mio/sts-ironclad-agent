import pathlib,json,time,sys,subprocess
r=pathlib.Path(__file__).resolve().parents[1]
while True:
 p=r/'evidence/smoke.jsonl'
 try:rows=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
 except json.JSONDecodeError:rows=[]
 if len(rows)==8:break
 time.sleep(15)
assert [x['seed'] for x in rows]==list(range(3000000000,3000000008))
assert all(x['error'] is None and x['c4r_calls'] for x in rows)
(r/'evidence/smoke-summary.json').write_text(json.dumps(dict(games=len(rows),errors=sum(x['error'] is not None for x in rows),heart_wins=sum(x['win'] for x in rows),seeds=[x['seed'] for x in rows],c4r_calls=sum(c['count'] for x in rows for c in x['c4r_calls']),heart2_calls=sum(c['count'] for x in rows for c in x['c4r_calls'] if c['act']==4)),indent=2))
subprocess.run([sys.executable,str(r/'tools/run_feed_cloud.py')],check=True)
subprocess.run([sys.executable,str(r/'tools/summarize_fixed.py'),str(r/'evidence/feed-fixed'),str(r/'evidence/feed-summary-linux.json')],check=True)
print('smoke and supplemental Feed validation completed',flush=True)
