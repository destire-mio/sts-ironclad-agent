from pathlib import Path
import json,hashlib,sys,shutil
r=Path(__file__).resolve().parents[1];out=r/'evidence/victory-hp';out.mkdir(exist_ok=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
parent=Path(sys.argv[1]).resolve();protected=json.loads((r/'parent-runtime-sha256.json').read_text());assert all(sha(parent/'runtime-delivery'/n)==h for n,h in protected.items())
old=r/'revisions/pre-victory-hp';previous=json.loads((old/'identity.json').read_text());order={};q_files={};old_files={}
for dataset in ['fixed','feed-fixed']:
 d=out/dataset;d.mkdir(exist_ok=True);cost=[]
 for p in sorted((old/dataset).glob('*-r.json')):
  x=json.loads(p.read_text());assert x.get('error') is None and 'replay' in x;old_files[dataset+'/'+p.name]=sha(p);cost.append((x['position'],x['cpu']*(2 if x.get('feed') or x['position']<8 else 1)))
  q=r/'evidence'/dataset/p.name.replace('-r.json','-q.json');cached=json.loads(q.read_text());assert cached.get('error') is None and 'replay' in cached;shutil.copy2(q,d/q.name);q_files[dataset+'/'+q.name]=sha(q)
 order[dataset]=[i for i,c in sorted(cost,key=lambda pair:(-pair[1],pair[0]))]
 for m,identity in [('r',previous),('q',json.loads((parent/'runtime-delivery/identity.json').read_text()))]:
  sample=next((r/'evidence'/dataset).glob('identity-'+m+'-*.json'));observed=json.loads(sample.read_text());assert observed['engine_sha256']==identity['engine_sha256'] and observed['fightsim_sha256']==identity['fightsim_sha256']
plan=dict(revision='victory-hp-20260929',runtime_identity=json.loads((r/'runtime-delivery/identity.json').read_text()),previous_4r_identity=previous,baseline_4q_identity=json.loads((parent/'runtime-delivery/identity.json').read_text()),baseline='reuse frozen same-platform 4q results; protected source/binary hashes verified; no new q search',order=order,previous_4r_files=old_files,baseline_4q_files=q_files,workers_max=8 if sys.platform=='darwin' else 4,ranking_metric='strict/tie order changes between previous/new 4r returned winning plans, rescored before and after HP projection under the same mechanics',validation_sources={n:sha(r/n) for n in ['tools/verify_victory_hp.py','tools/paired_io.cpp','tools/victory_hp_contract.cpp']})
p=out/'plan.json';assert not p.exists();p.write_text(json.dumps(plan,indent=2))
expected={str(p.relative_to(r)):sha(p) for folder in ['agent','engine-source'] for p in (r/folder).rglob('*') if p.suffix in ['.cpp','.h']};(out/'expected-cpp-sha256.json').write_text(json.dumps(expected,indent=2));print('planned',len(order['fixed']),len(order['feed-fixed']),len(expected),'C++ files')
